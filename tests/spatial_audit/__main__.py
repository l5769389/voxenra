"""PYTHONPATH=src:tests python -m spatial_audit --output build/spatial-audit."""
import argparse
import json
import platform
import subprocess
import traceback
from pathlib import Path
from .cases import CASES, generate
from .verify import verify_case


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    results=[]
    for case in CASES:
        root=args.output/case.name
        generate(root,case)
        try: result=verify_case(root)
        except Exception:
            result=dict(case=case.name,status='failure',reason=traceback.format_exc())
            (root/'voxenra-result.json').write_text(json.dumps(result,indent=2))
        results.append(result);print(case.name,result['status'],flush=True)
    report=dict(schema=1,python=platform.python_version(),
        commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),cases=results)
    (args.output/'voxenra-summary.json').write_text(json.dumps(report,indent=2))
    return int(any(r['status']=='failure' for r in results))

if __name__=='__main__': raise SystemExit(main())
