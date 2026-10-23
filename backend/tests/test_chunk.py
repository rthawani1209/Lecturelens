from lecturelens.pipeline.chunk import Sentence, windows


def test_windows_overlap_and_cover_everything():
    sents = [Sentence(t, t + 10, f"s{t}") for t in range(0, 60, 10)]  # 0-60s, 10s each
    ws = windows(sents, size_s=30, stride_s=15)
    assert [(w.start_s, w.end_s) for w in ws] == [(0, 30), (10, 50), (30, 60)]
    assert ws[0].text == "s0 s10 s20"
    covered = {s.text for w in ws for s in sents if s.text in w.text}
    assert covered == {s.text for s in sents}


def test_windows_short_lecture_and_empty():
    assert windows([]) == []
    ws = windows([Sentence(1, 4, "hello")])
    assert len(ws) == 1 and ws[0].text == "hello"
