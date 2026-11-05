"""Fill-in-the-blank cards, the fallback when there's no API key."""

from lecturelens.study.cards import cloze, key_terms, sentences


def line(t, text, end=None):
    return {"start_s": t, "end_s": end if end is not None else t + 30, "text": text}


def test_sentences_drop_pieces_cut_off_by_line_breaks():
    lines = [
        line(0, "and the set interface. A heap is a complete binary tree stored in an", 20),
        line(
            20, "array. Every parent is at least as big as its children, the max heap property.", 40
        ),
    ]
    got = sentences(lines)
    assert [s for _, s in got] == [
        "Every parent is at least as big as its children, the max heap property."
    ]
    assert got[0][0] > 20  # timed from its place in the line, not the line start


LECTURE = [
    line(0, "Alright, welcome back to data structures, today we cover the binary heap."),
    line(100, "Any questions about the problem set before we start on the heap?"),
    line(400, "A heap is a complete binary tree where every parent beats its children."),
    line(700, "To insert we add the item at the end of the array and swap it up the tree."),
    line(1000, "Swap swap swap, we swap until the heap property holds again at the root."),
    line(1300, "Heaps never need rotations, because the shape of the tree is always fixed."),
    line(1600, "The height of the tree is log n, so each operation costs log n swaps total."),
    line(1900, "Data structures like this one store data so data can be found quickly later."),
]


def test_cloze_skips_the_opening_and_chatter_and_blanks_one_rare_term():
    terms = key_terms(
        {"heap": 5.0, "heaps": 4.0, "data": 6.0, "swap": 3.0, "height": 2.0},
        rarity={"heap": 2.7, "heaps": 2.7, "data": 1.0, "swap": 1.9, "height": 2.0},
        lectures=21,
    )
    assert "data" not in terms  # said in nearly every lecture
    assert "heaps" not in terms  # same term as "heap"
    cards = cloze(LECTURE, terms)
    fronts = " ".join(c["front"] for c in cards)
    assert "welcome" not in fronts.lower() and "problem set" not in fronts
    assert all(c["front"].count("_____") == 1 for c in cards)
    assert {c["back"] for c in cards} == {"heap", "swap", "height"}
    # the sentence that says what a heap is, and not "swap swap swap"
    by = {c["back"]: c["front"] for c in cards}
    assert by["heap"].startswith("A _____ is a complete binary tree")
    assert by["swap"].startswith("To insert")
    assert len({c["front"] for c in cards}) == len(cards)


def test_hyphenated_words_stay_whole():
    lines = [
        line(0, "Opening remarks go here and are skipped by the cloze builder."),
        line(500, "Dijkstra needs non-negative weights on every single edge of the graph."),
        line(900, "A negative weight on an edge breaks the algorithm in subtle ways."),
    ]
    cards = cloze(lines, ["negative"])
    assert [c["front"] for c in cards] == [
        "A _____ weight on an edge breaks the algorithm in subtle ways."
    ]
