# LectureLens: talking about it

Plain-English answers to the questions an interviewer is likely to ask. Every number
here is in [CLAIMS.md](CLAIMS.md) with the command that reproduces it.

## Search: "Did the machine-learned re-ranker work?"

Partly, and the honest answer is the interesting part.

Search combines four retrievers (keyword, meaning, slide text, image) with reciprocal
rank fusion, then a small Keras network trained with a pairwise loss re-orders the top
results. Two things moved the numbers on held-out MIT 6.006 lectures: tuning the fusion
weights on val took hybrid NDCG@10 from 0.655 to 0.719, and the re-ranker took recall@5
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

## Search: "Did the re-ranker help?"

Only on recall. With it, the right moment shows up in the top 5 for 88.2% of test
questions instead of 81.6%, the best of any method. But it doesn't put that moment
higher in the list: NDCG@10 stayed flat (0.719 to 0.720) and MRR dipped slightly. It
did beat the simpler logistic regression baseline (0.696 NDCG@10), so the pairwise
network was worth more than a linear model on the same features. The bigger NDCG gain
came from tuning the fusion weights, not from the model.
