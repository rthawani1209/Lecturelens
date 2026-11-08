# LectureLens: talking about it

Plain-English answers to the questions an interviewer is likely to ask. Every number
here is in [CLAIMS.md](CLAIMS.md) with the command that reproduces it.

## Search: "Did the machine-learned re-ranker work?"

Partly, and the honest answer is the interesting part.

Search combines four retrievers (keyword, meaning, slide text, image) with reciprocal
rank fusion, then a small Keras network trained with a pairwise loss re-orders the top
results. Two things moved the numbers on held-out MIT 6.006 lectures: tuning the fusion
weights on val took hybrid NDCG@10 from 0.665 to 0.720, and the re-ranker took recall@5
from 81.6% to 88.2%.

But plain meaning search on its own scored 0.786, better than everything combined. I
made every choice on a separate validation set, with a rule written down beforehand:
switch the default only if something beats meaning-only on val by 0.01. The re-ranker
tied (0.759 vs 0.756), so meaning-only ships as the default and a CI gate fails the
build if the default ever drops below any single retriever.

Why it lost: I had no real student questions to train on, so I generated them from the
lecture's own sentences. Those queries share rare words with the right answer, so the
model learned to trust keyword overlap. Real questions paraphrase, which is exactly
what meaning search is good at. More data of the wrong kind made it worse (doubling the
generated queries lowered val NDCG). The next step would be paraphrased training
questions, not a bigger model. And on a lecture course that is mostly chalkboard and
speech, slide text and images just don't add much; hybrid stays available for
slide-heavy courses.

## Search: "Does it work on other courses?"

I labeled 15-16 questions on three lectures each of two courses I never tuned on: MIT
6.100L (intro Python, slide-heavy) and 18.06 (Strang's linear algebra, all
chalkboard). The default, meaning search, held up: 0.834 NDCG@10 on 18.06, the best of
every method, and 0.775 on 6.100L. The Python course is where it lost: the best there
was hybrid search with my original day 3 weights (0.848), which count the text on the
slides, and keyword plus meaning was close (0.836). Tuning on chalkboard-heavy 6.006
had set the slide text weight to zero, so those tuned weights didn't carry over to a
slide course (0.786). That's a fair warning about tuning on one course, and a reason
to keep hybrid as an option. The sets are small, so I treat them as a sanity check, not a headline
number.

## Search: "Did the re-ranker help?"

Only on recall. With it, the right moment shows up in the top 5 for 88.2% of test
questions instead of 81.6%, the best of any method. But it doesn't put that moment
higher in the list: NDCG@10 stayed flat (0.720 to 0.718) and MRR dipped slightly. It
did beat the simpler logistic regression baseline (0.696 NDCG@10), so the pairwise
network was worth more than a linear model on the same features. The bigger NDCG gain
came from tuning the fusion weights, not from the model.

## Study: "How do the flashcards and Ask work without hallucinating?"

Ask only answers from the lecture. It pulls the closest transcript passages (keyword
and meaning search, merged the same way as search), numbers them, and sends them to
Claude as quoted data with a JSON schema: every sentence has to cite at least one
passage. I drop any sentence without a valid citation, and if nothing survives the
answer is "not covered in this lecture" with a link to search the whole course. Text
inside a transcript that looks like an instruction stays data; there's a test that
plants one and checks it's ignored.

Without an API key (CI, or someone running it locally) it still works: Ask quotes the
two best on-topic sentences, and flashcards become fill-in-the-blank cards. Those pick
terms that are rare across the course and were both said and shown on a slide, which
filters out filler words. Reviews use SM-2, the classic spaced repetition schedule.

Every AI call is logged per user with its token count, and there are limits per
minute, day and month, so one user can't run up the bill.

## Testing: "How do you know the UI works?"

Unit tests cover the backend (pytest) and the upload client (Vitest), but the thing I
trust most is the Playwright suite. `scripts/e2e.sh` starts the real stack (API,
Celery worker, Postgres, Redis, the production Next.js build), seeds a short generated
lecture through the real pipeline, and clicks every control on every screen. Any
console error fails the test. The upload test kills a chunk's connection twice,
cancels, resumes, waits for the live pipeline to finish, and then searches for
something said in the video. There is also a pass at phone width (390 px).

It found a real bug: Next.js compressed the progress stream, which buffered it, so the
pipeline screen sat still until processing finished. Adding `Cache-Control:
no-transform` fixed it, and a backend test now checks the header.

What's mocked: the YouTube download. CI can't depend on YouTube, so a manual workflow
runs a real import instead.

## Deploy: "Is the live demo using TF Serving?"

No, and I'd say so up front. TF Serving runs the tagger and the re-ranker on x86 and in
CI, but the free host is an ARM machine (Oracle Cloud), and `tensorflow/serving` has no
arm64 image. So there the worker runs the same weights in-process: the tagger as an
ONNX export through onnxruntime, the re-ranker in NumPy. Tests check both match Keras
to 1e-4, and CI runs the full deploy smoke test on x86 and on ARM.
