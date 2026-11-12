"""Homepage previews retain animation semantics while avoiding excess bytes."""
from io import BytesIO
from PIL import Image, ImageDraw
from test_manual_site import SITE


def test_animation_reuses_unchanged_background_without_losing_frames(tmp_path):
    background=Image.effect_noise((360,240),60).convert('RGB')
    frames=[]
    for x in range(0,100,10):
        frame=background.copy();ImageDraw.Draw(frame).rectangle((x,20,x+15,40),fill='red');frames.append(frame)
    source=tmp_path/'motion.gif'
    frames[0].save(source,save_all=True,append_images=frames[1:],duration=[100]*10,loop=2)
    # Compare the exact same decoded/resize input with the previous encoder.
    with Image.open(source) as im:
        from PIL import ImageSequence
        decoded=[f.convert('RGBA') for f in ImageSequence.Iterator(im)]
    baseline=BytesIO()
    decoded[0].save(baseline,format='WEBP',quality=82,method=6,save_all=True,append_images=decoded[1:],duration=[100]*10,loop=2)
    optimized=SITE.encode_webp(source,'performance-fixture',360)
    assert len(optimized) < len(baseline.getvalue()) * .9
    with Image.open(BytesIO(optimized)) as result:
        assert result.n_frames==10 and result.info['loop']==2
        for i in range(10):
            result.seek(i);result.load()
            assert result.info['duration']==100
            r,g,b,*_=result.getpixel((i*10+7,27))
            assert r>g+60 and r>b+60


def test_phone_candidates_do_not_start_at_desktop_thumbnail_width():
    widths=[width for width,_,_ in SITE.product_image_variants('hero-mpr.png')]
    assert 320 in widths and 480 in widths
    assert 960 in widths and max(widths)>=1000
