# Vocabulary round

Quiz the learner on due words from the deck, then test comprehension with a short passage spoken the way their teacher would speak it.

## The deck

`~/Portuguese/vocabulary.md` is a markdown table, one row per word or phrase:

| português | English | box | last seen | source |
|---|---|---|---|---|
| ouça e repita | listen and repeat | 1 | 2026-11-05 | IMG_2276 |

- **português**: the lemma with its article for nouns (`a casa`), the infinitive for verbs, or a whole fixed phrase.
- **box**: Leitner box 1–5. A word is **due** when the days since `last seen` reach the box's interval: 1 → 0, 2 → 1, 3 → 3, 4 → 7, 5 → 14. Right answer: box +1 (max 5). Wrong: back to box 1.
- **source**: the screenshot filename without its extension, or `class` for words the learner adds.

## Steps

1. **Load the deck.** Create the deck if missing. Harvest every screenshot that no row names as its source: add each new noun, verb, adjective, question word and fixed phrase, and every **classroom phrase**, the exercise instructions the teacher speaks aloud (*ouça e repita*, *faça a correspondência*, *trabalho de pares*). New rows start in box 1. If the argument is `add <words>`, add those words as `class` rows, glossing them yourself. Done when every screenshot is named as a source in at least one row.
2. **Pick the words.** Ten due words, lowest box first, then oldest `last seen`, with `class` and classroom-phrase rows first among equals. If the argument is `vocab <topic>`, pick from rows on that topic. If fewer than ten are due, top up with the lowest-box rows.
3. **Quiz.** Number the ten in one list: about seven Portuguese → English (comprehension, the learner's weak spot) and three English → Portuguese. Stop and wait for all the answers in one reply.
4. **Grade the quiz.** For each word: right or wrong, the correct answer, and for a wrong one a short hook to remember it (a cognate, a sentence from the lessons). Count a missing accent or a wrong article as wrong in English → Portuguese; in Portuguese → English, accept any fitting meaning.
5. **Passage.** Three or four sentences of Portuguese as the teacher would say them in class, built from the quiz words, other deck words and syllabus grammar. Ask the learner what it means in English. Stop and wait.
6. **Grade the passage.** Give the English meaning sentence by sentence and name each word the learner missed or misread. Words they missed in the passage count as wrong for their boxes.
7. **Update and log.** Update `box` and `last seen` for every word quizzed or missed in the passage. Append the log line (`vocab (<topic or "due">) — mistakes: <word→meaning, …>`) and offer the next round.
