from qt_dicom_viewer.ui.controller.viewport.operation.scroll_operation import ScrollOperation


def test_pixel_wheel_accumulates_reverses_and_clamps():
    op = ScrollOperation()
    def scroll(pixel, index=5):
        return op.handle_wheel(angle_delta_y=0, pixel_delta_y=pixel,
                               current_index=index, slice_count=10)
    assert scroll(-20) is None
    assert scroll(-20) is None
    assert scroll(-20).slice_index == 6
    assert scroll(-40) is None
    assert scroll(30) is None  # direction change discards the previous remainder
    assert scroll(30).slice_index == 4
    assert scroll(-600).slice_index == 9
    assert scroll(600).slice_index == 0
    op.reset()
    assert scroll(30) is None


def test_wheel_units_do_not_mix_or_double_count():
    op = ScrollOperation()
    def scroll(angle=0, pixel=0):
        return op.handle_wheel(angle_delta_y=angle, pixel_delta_y=pixel,
                               current_index=5, slice_count=10)
    assert scroll(pixel=-30) is None
    assert scroll(angle=-60) is None  # discard pixel remainder when device/unit changes
    assert scroll(angle=-60).slice_index == 6
    assert scroll(angle=-120, pixel=-60).slice_index == 6
    assert scroll(angle=0, pixel=0) is None
