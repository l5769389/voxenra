"""Application-wide local inference job; results belong to their captured tab/phase."""
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Mapping
from pathlib import Path
from threading import Event
import json
import shutil
import sys
import tempfile
import weakref

from PySide6.QtCore import QObject, Property, Signal, Slot, QTimer, QStandardPaths, QLockFile
from qt_dicom_viewer.i18n import message as _msg
from qt_dicom_viewer.i18n.messages import error_message, localize
from qt_dicom_viewer.i18n.qt import translated_property
from qt_dicom_viewer.i18n.widgets import QFileDialog
from qt_dicom_viewer.core.local_segmentation import DEFAULT_ORGANS, validate_input, read_results
from qt_dicom_viewer.core.nrrd_exchange import write_nrrd
from qt_dicom_viewer.core.workspace_state import dumps, MAX_MASK_VOXELS
from qt_dicom_viewer.infrastructure.local_inference_process import run_process
from qt_dicom_viewer.infrastructure.local_segmentation_environment import discover_python, discover_weights, normalize_weights


def _string_list(value, *, nonempty=False):
    return (isinstance(value, list) and (bool(value) or not nonempty)
            and all(isinstance(item, str) and item.strip() for item in value))


def _valid_probe(result):
    if not isinstance(result, Mapping):
        return False
    organs, devices = result.get('organs'), result.get('devices')
    return (type(result.get('protocol')) is int and result['protocol'] == 1
            and type(result.get('model_ready')) is bool
            and _string_list(organs, nonempty=True) and len(set(organs)) == len(organs)
            and _string_list(devices, nonempty=True) and len(set(devices)) == len(devices)
            and set(devices) <= {'cpu', 'gpu', 'mps'}
            and ('version' not in result or isinstance(result['version'], str) and bool(result['version'].strip()))
            and ('model_issues' not in result or _string_list(result['model_issues'])))


def _validate_event(event):
    if not isinstance(event, Mapping) or not isinstance(event.get('event'), str) or not event['event'].strip():
        raise RuntimeError(_msg('autoSeg.invalidResponse'))
    kind = event['event']
    if (kind == 'stage' and event.get('stage') not in ('running', 'validating')
            or kind == 'error' and (not isinstance(event.get('reason'), str) or not event['reason'].strip())
            or kind == 'model' and not _string_list(event.get('issues'))):
        # RuntimeError must propagate through run_process's JSON parse error handling.
        raise RuntimeError(_msg('autoSeg.invalidResponse'))
    return kind


class LocalSegmentationController(QObject):
    _i18n_message = Signal()
    _i18n_environmentMessage = Signal()
    _i18n_compatibilityMessage = Signal()
    _i18n_organs = Signal()
    _i18n_targetTitle = Signal()
    changed = Signal()
    completed = Signal(object)
    stageChanged = Signal(str)

    def __init__(self, settings, catalog, parent=None, *, cache=None):
        super().__init__(parent)
        self.settings, self.catalog = settings, catalog
        self._temporary_cache = tempfile.TemporaryDirectory(prefix='voxenra-local-segmentation-') if cache is False else None
        self._cache = Path((self._temporary_cache.name if self._temporary_cache else cache) or Path(QStandardPaths.writableLocation(QStandardPaths.CacheLocation)) / 'local-segmentation')
        try:
            self._cache.mkdir(parents=True,exist_ok=True)
        except OSError:
            pass  # An unavailable optional-service cache must not block application startup.
        self._state='idle';self._message='';self._logs='';self._environment={}
        self._environment_state='idle';self._environment_message=''
        self._discovered_python=None
        self._target=None;self._pending=None;self._closed=False;self._title=''
        self._cancel=Event();self._executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='local-segmentation')
        self._future=None;self._epoch=0
        self.completed.connect(self._receive)
        self.stageChanged.connect(self._stage)
        self._timer=QTimer(self);self._timer.setInterval(250);self._timer.timeout.connect(self._poll_target)
        settings.sectionChanged.connect(self._settings_changed)
        self._cleanup_stale()

    def _cleanup_stale(self):
        for path in self._cache.glob('job-*'):
            if path.is_dir() and not path.is_symlink():
                lock=QLockFile(str(path/'owner.lock'))
                if lock.tryLock(0):
                    lock.unlock()
                    shutil.rmtree(path,ignore_errors=True)

    @Property(str,notify=changed)
    def state(self): return self._state
    @Property(bool,notify=changed)
    def busy(self): return self._state in ('checking','prepare','running','validating','pending','importing','cancelling')
    @translated_property(str,notify=_i18n_message,notify_name='_i18n_message',source_notify='changed')
    def message(self): return self._message or _msg('autoSeg.'+self._state)
    @Property(str,notify=changed)
    def logs(self): return self._logs
    @translated_property(str,notify=_i18n_targetTitle,notify_name='_i18n_targetTitle',source_notify='changed')
    def targetTitle(self): return self._title
    @Property('QVariantMap',notify=changed)
    def environment(self): return self._environment
    @Property(bool,notify=changed)
    def hasTarget(self): return self._target is not None
    @Property(QObject,notify=changed)
    def targetTab(self): return self._target[0]() if self._target is not None else None
    @Property(int,notify=changed)
    def targetPhase(self): return self._target[3] if self._target is not None and self._target[3] is not None else -1
    @Property(bool,notify=changed)
    def ready(self): return bool(self._environment.get('model_ready'))
    @translated_property('QVariantList',notify=_i18n_organs,notify_name='_i18n_organs',source_notify='changed')
    def organs(self):
        selected=set(self.settings.values['services']['segmentationOrgans'])
        from qt_dicom_viewer.i18n.messages import builtin
        known=builtin()['messages']
        return [dict(id=key,name=_msg('autoSeg.organ.'+key) if 'autoSeg.organ.'+key in known else key.replace('_',' '),
            selected=key in selected) for key in self._environment.get('organs',[])]
    @Property('QVariantList',notify=changed)
    def devices(self):
        selected=self.settings.values['services']['segmentationDevice']
        return list(dict.fromkeys(['auto',*self._environment.get('devices',[]),selected]))
    @Property(bool,notify=changed)
    def deviceAvailable(self):
        selected=self.settings.values['services']['segmentationDevice']
        return selected=='auto' or selected in self._environment.get('devices',[])
    @Property(str,notify=changed)
    def environmentState(self): return self._environment_state
    @translated_property(str,notify=_i18n_environmentMessage,notify_name='_i18n_environmentMessage',source_notify='changed')
    def environmentMessage(self):
        return self._environment_message or _msg('autoSeg.'+self._environment_state)
    @translated_property(str,notify=_i18n_compatibilityMessage,notify_name='_i18n_compatibilityMessage',source_notify='changed')
    def compatibilityMessage(self):
        if not self._environment.get('version'):return ''
        selected=self.settings.values['services']['segmentationDevice']
        devices=self._environment.get('devices',[])
        effective=devices[0] if selected=='auto' and devices else selected
        verified=(effective=='mps' and sys.platform=='darwin' and self._environment['version']=='2.18.0'
                  and 'mps' in self._environment.get('devices',[]))
        return _msg('autoSeg.compatibilityVerified' if verified else 'autoSeg.compatibilityUnchecked')
    @Property(str,notify=changed)
    def pythonPath(self): return self._configuration()[0]
    @Property(str,notify=changed)
    def weightsPath(self): return self._configuration()[1]

    def _settings_changed(self, section):
        if section=='services':
            config=self._configuration()
            if config != getattr(self,'_checked_config',None):
                self._environment={}
                self._environment_state='idle';self._environment_message=''
        self.changed.emit()

    def _configuration(self):
        values=self.settings.values['services']
        if self._discovered_python is None:
            self._discovered_python=discover_python()
        python=values['segmentationPython'] or self._discovered_python
        weights=values['segmentationWeights'] or discover_weights(python)
        return python,str(normalize_weights(weights))

    @Slot()
    def resetEnvironment(self):
        if self.busy:return
        self.settings.setValue('services','segmentationPython','')
        self.settings.setValue('services','segmentationWeights','')
        self._discovered_python=None
        self.checkEnvironment()

    @Slot()
    def choosePython(self):
        if self.busy:return
        path,_=QFileDialog.getOpenFileName(None,_msg('autoSeg.pythonPicker'),self._configuration()[0],
            options=QFileDialog.Option.DontResolveSymlinks)
        if path:self.settings.setValue('services','segmentationPython',path)
    @Slot()
    def chooseWeights(self):
        if self.busy:return
        path=QFileDialog.getExistingDirectory(None,_msg('autoSeg.weights'),self._configuration()[1])
        if path:self.settings.setValue('services','segmentationWeights',str(normalize_weights(path)))
    @Slot(str,bool)
    def selectOrgan(self,key,selected):
        if self.busy or key not in self._environment.get('organs',[]):return
        values=list(self.settings.values['services']['segmentationOrgans'])
        values=[v for v in values if v!=key]
        if selected:values.append(key)
        self.settings.setValue('services','segmentationOrgans',values)
    @Slot(bool)
    def selectAll(self,selected):
        if not self.busy:self.settings.setValue('services','segmentationOrgans',self._environment.get('organs',[]) if selected else [])

    @Slot(QObject,result=bool)
    def prepare(self,tab):
        if self.busy:return self._target is not None
        try:
            view=getattr(tab,'activeViewport',None)
            voi=getattr(tab,'_voi_controller',None)
            volume=getattr(view,'_voi_volume',None)
            if (tab is None or str(tab.tab_config.tab_type) not in ('mpr','4d') or voi is None or volume is None
                    or not voi._phase_ready or voi._closed or getattr(view,'render_pending',False)):
                raise ValueError(_msg('autoSeg.noTarget'))
            series=self.catalog.get_series(volume.series_uid)
            if series is None or series.modality!='CT' or volume.pixel_value_meta.unit.upper()!='HU':
                raise ValueError(_msg('autoSeg.unsupported'))
            tab_ref = weakref.ref(tab)
            if self._target is None or self._target[0] != tab_ref:
                tab.destroyed.connect(lambda: self._target_destroyed(tab_ref))
            self._target=(tab_ref,weakref.ref(voi),volume,voi._phase,series)
            self._title=series.series_description or 'CT'
            if voi._phase is not None:self._title+=' · '+_msg('autoSeg.phase',phase=voi._phase+1)
            self._pending=None;self._state='ready' if self.ready else 'idle';self._message=''
            self.changed.emit()
            return True
        except (ValueError,RuntimeError) as error:
            self._target=None;self._fail(error);return False

    def _target_destroyed(self, tab_ref):
        if self._closed or self._target is None or self._target[0] != tab_ref:
            return
        self._target = None
        self._pending = None
        if self.busy:
            self.cancel()
        self.changed.emit()

    @Slot()
    def checkEnvironment(self):
        if self.busy or self._closed:return
        self._discovered_python=None
        python,weights=self._configuration()
        self._environment={};self._environment_state='checking';self._environment_message=''
        if not Path(python).is_file():
            self._environment_state='error';self._environment_message=_msg('autoSeg.missingPython')
            self._fail(self._environment_message);return
        self._checked_config=(python,weights)
        self._environment={};self._start('checking','probe',dict(weights=weights),python)

    @Slot()
    def start(self):
        if self.busy or self._closed:return
        if not self._target:self._fail(_msg('autoSeg.noTarget'));return
        if not self.ready:self.checkEnvironment();return
        if not self.deviceAvailable:self._fail(_msg('autoSeg.deviceUnavailable'));return
        organs=self.settings.values['services']['segmentationOrgans']
        if not organs:self._fail(_msg('autoSeg.selection'));return
        if not set(organs)<=set(self._environment['organs']):self._fail(_msg('autoSeg.selection'));return
        if self._target_status()!='ready':self._fail(_msg('autoSeg.changed'));return
        python,weights=self._configuration()
        request=dict(weights=weights,organs=organs,device=self.settings.values['services']['segmentationDevice'])
        self._start('prepare','run',request,python)

    def _start(self,state,mode,request,python):
        self._cancel=Event();self._epoch+=1;epoch=self._epoch
        self._state=state;self._message='';self._logs='';self._pending=None
        target=self._target;cancel=self._cancel
        self.changed.emit()
        if mode=='run':self._timer.start()
        def work():
            root=Path(tempfile.mkdtemp(prefix='job-',dir=self._cache))
            lock=QLockFile(str(root/'owner.lock'));lock.lock()
            log=root/'worker.log'
            result=None;error=None;bridge_errors=[]
            try:
                if mode=='run':
                    volume=target[2];series=target[4]
                    validate_input(volume,series.modality)
                    write_nrrd(root/'source.nrrd',volume.modality_pixels,volume.geometry.voxel_to_patient,cancelled=cancel.is_set)
                (root/'request.json').write_text(json.dumps(request),encoding='utf-8')
                # A data resource: never statically import the external runtime.
                bridge=Path(__file__).resolve().parents[2] / 'infrastructure/totalsegmentator_bridge.py'
                if not bridge.is_file():raise FileNotFoundError('TotalSegmentator bridge resource is missing')
                def receive(event):
                    if self._closed or cancel.is_set() or epoch != self._epoch:
                        return
                    kind = _validate_event(event)
                    if kind == 'error':
                        bridge_errors.append(event['reason'][:500])
                    if mode == 'run' and kind == 'stage':
                        self.stageChanged.emit(event['stage'])
                run_process([python,str(bridge),mode,str(root)],log,cancel,receive,timeout=120 if mode=='probe' else None)
                if cancel.is_set():raise InterruptedError()
                if bridge_errors:raise RuntimeError(bridge_errors[-1])
                if mode=='probe':result=json.loads((root/'result.json').read_text())
                else:result=read_results(root,target[2],request['organs'],phase=target[3],cancelled=cancel.is_set)
            except Exception as exc:
                error=RuntimeError(bridge_errors[-1]) if bridge_errors and not isinstance(exc,InterruptedError) else exc
            finally:
                logs = ''
                try:
                    if log.exists():
                        with log.open('rb') as stream:
                            stream.seek(max(0, log.stat().st_size - 16000))
                            logs = stream.read(16000).decode('utf-8', errors='replace')
                    # Diagnostics must never prevent image cleanup or hide the original error.
                    (self._cache/'last-run.log').write_text(logs,encoding='utf-8')
                except OSError:
                    pass
                finally:
                    lock.unlock()
                    shutil.rmtree(root,ignore_errors=True)
            return epoch,mode,result,error,logs
        self._future=self._executor.submit(work)
        def done(future):
            try:payload=future.result()
            except Exception as error:payload=(epoch,mode,None,error,'')
            if not self._closed:self.completed.emit(payload)
        self._future.add_done_callback(done)

    @Slot(str)
    def _stage(self,stage):
        if self.busy and not self._cancel.is_set() and stage in ('running','validating'):
            self._state=stage;self.changed.emit()

    @Slot(object)
    def _receive(self,payload):
        epoch,mode,result,error,logs=payload
        if self._closed or epoch!=self._epoch:return
        self._logs=logs
        if mode=='probe':
            self._environment={}
            self._environment_state='error' if error is not None else 'idle'
            self._environment_message=error_message(error) if error is not None else ''
        if self._cancel.is_set() or isinstance(error,InterruptedError):
            if mode=='probe':self._environment_state='idle';self._environment_message=''
            self._state='cancelled';self._message='';self._pending=None;self._timer.stop();self.changed.emit();return
        if error is not None:self._fail(error);return
        if mode=='probe':
            if self._configuration() != self._checked_config:
                self._environment_state='idle';self._environment_message=''
                self._fail(_msg('autoSeg.environmentChanged'));return
            if not _valid_probe(result):
                self._environment_state='error';self._environment_message=_msg('autoSeg.invalidResponse')
                self._fail(self._environment_message);return
            self._environment=dict(result)
            self._state='ready' if self.ready else 'error'
            self._message='' if self.ready else _msg('autoSeg.missingModel')
            self._environment_state=self._state;self._environment_message=self._message
            self.changed.emit()
        else:
            self._pending=result;self._state='pending';self._poll_target()

    def _target_status(self):
        if self._target is None:return 'invalid'
        tab_ref,voi_ref,volume,phase,series=self._target
        tab,voi=tab_ref(),voi_ref()
        if tab is None or voi is None or voi._closed:return 'invalid'
        # Catalog identity is immutable; replacements must not inherit old results.
        if self.catalog.get_series(volume.series_uid) is not series:return 'invalid'
        if voi._phase!=phase or not voi._phase_ready:return 'pending'
        current=voi.sources.get(volume.series_uid)
        if (current is None or current.fingerprint!=volume.fingerprint or current.geometry!=volume.geometry
                or (not volume.fingerprint and current.modality_pixels is not volume.modality_pixels)):
            return 'invalid'
        if voi._draft or voi.busy:return 'pending'
        return 'ready'

    @Slot()
    def _poll_target(self):
        if self._closed or self._target is None:return
        status=self._target_status()
        if status=='invalid':
            self._cancel.set();self._pending=None
            if self._future is None or self._future.done():self._fail(_msg('autoSeg.changed'))
            return
        if self._pending is None:return
        if status!='ready':self._state='pending';self.changed.emit();return
        try:
            voi=self._target[1]();records,evaluations,empty=self._pending
            if sum(r['mask'].size for r in [*voi.records,*records] if 'mask' in r)>MAX_MASK_VOXELS:
                raise ValueError(_msg('seg.tooLarge'))
            # Unique colors without changing existing records or committing partial data.
            from PySide6.QtGui import QColor
            used={QColor(r['color']).name().lower() for r in voi.records}
            palette=('#ed55ed','#43c6dc','#ffbb55','#87d980','#ff7070','#9292ff','#e6dc65','#5fe0b3')
            names={o['id']:o['name'] for o in self.organs}
            for i,record in enumerate(records):
                color=next((c for c in palette if c not in used),QColor.fromHsv((len(used)*137)%360,170,240).name())
                used.add(color);record['color']=color;record['name']=names.get(record['name'],record['name'])
            dumps({'voi':[*voi.records,*records]})
            self._state='importing';self.changed.emit()
            voi.add_masks(records,evaluations)
            self._pending=None;self._state='done';self._timer.stop()
            self._message=_msg('autoSeg.done',count=len(records))
            if empty:self._message=self._message+'\n'+_msg('autoSeg.emptySome',organs=', '.join(names.get(o,o) for o in empty))
            self.changed.emit()
        except Exception as error:self._fail(error)

    def _fail(self,error):
        self._pending=None;self._state='error';self._timer.stop()
        self._message=_msg('autoSeg.failed',reason=error_message(error) if isinstance(error,Exception) else error)
        self.changed.emit()

    @Slot()
    def cancel(self):
        self._cancel.set();self._pending=None
        self._timer.stop()
        if self._future is None or self._future.done():self._state='cancelled'
        else:self._state='cancelling'
        self._message=_msg('autoSeg.cancelled');self.changed.emit()

    def shutdown(self):
        if self._closed:return
        self._closed=True;self._cancel.set();self._timer.stop();self._pending=None
        self._executor.shutdown(wait=True,cancel_futures=True)
        self._target=None
        if self._temporary_cache:self._temporary_cache.cleanup()
