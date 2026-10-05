# Headings that state a number and count nothing

Every one of these is copied from a real README in the portfolio, and every one was
reported as drift. Together they were 11 of 25 counted headings — a checker wrong
44% of the time, which is a checker nobody should believe.

## Result 3 — the average is carried by four trivial cases

| Case | Edits | Exact | Note |
|---|---|---|---|
| a | 1 | yes | - |
| b | 2 | no | - |
| c | 3 | yes | - |
| d | 4 | no | - |
| e | 5 | yes | - |
| f | 6 | no | - |
| g | 7 | yes | - |
| h | 8 | no | - |
| i | 9 | yes | - |
| j | 10 | no | - |
| k | 11 | yes | - |

## Finding 5 in detail: how many reads reach the model

| Read | Reached |
|---|---|
| one | yes |
| two | no |
| three | yes |
| four | no |

## There aren't 200 sources. There are about ten.

| Source | Kind |
|---|---|
| a | board |
| b | board |
| c | feed |
| d | feed |

## F1 with 95% bootstrap CI

| Split | F1 | Low | High |
|---|---|---|---|
| dev | 0.81 | 0.78 | 0.84 |
| test | 0.79 | 0.75 | 0.83 |
| hard | 0.61 | 0.55 | 0.67 |
| easy | 0.93 | 0.90 | 0.96 |
| all | 0.80 | 0.77 | 0.83 |
| pooled | 0.80 | 0.77 | 0.83 |
| macro | 0.78 | 0.74 | 0.82 |
| micro | 0.80 | 0.77 | 0.83 |

## Failure categories (web2md, all 3,975 pages)

| Category | Pages |
|---|---|
| boilerplate | 1,204 |
| nav kept | 902 |
| table lost | 611 |
| code mangled | 540 |
| encoding | 418 |
| other | 300 |

## What it scores, on 47 questions with `qwen2.5-coder:14b`

- exact match: 0.62
- executable: 0.81

## The model arm: qwen2.5-coder:14b under three prompt shapes

- terse
- explained
- chain-of-thought

## 04 · The injection that isn't an instruction

| Payload | Blocked |
|---|---|
| a | yes |
| b | yes |
| c | no |

## Top 5 findings

- one
- two
- three

## 2026-09-16 · qwen2.5-coder:14b added

| Model | Added |
|---|---|
| 14b | yes |
| 3b | yes |

## Six tabs

| Tab | Shows |
|---|---|
| one | a |
| two | b |
| three | c |
| four | d |
| five | e |
| six | f |
