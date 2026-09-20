# Historical backtest (nflverse 2015-2025, PSL scoring)

Generated 2026-09-20T21:36:08Z. Status: OK.

## Scoring gate (week 1, 2026)

Offense: 357 players compared, 0 outside 0.1. DEF: 32 compared, 0 outside 0.1.

## Scope

63,387 offensive player-weeks and 5,790 defense-weeks, seasons 2015-2025. Fit 2015-2019, select 2020-2024, held-out 2025. 36 configurations tried.

## Held-out season 2025

| Model | n | MAE (all) | MAE (starter-caliber) | n starters | Bias (starters) | RMSE | Spearman (mean/week) | Lineup pts / team-week | % of optimal |
|---|---|---|---|---|---|---|---|---|---|
| naive | 5,749 | 4.51 | 6.62 | 1,530 | -1.64 | 6.57 | 0.603 | 91.98 | 88.2 |
| kblend:4 | 5,749 | 4.42 | 6.31 | 1,530 | -0.72 | 6.34 | 0.607 | 93.09 | 89.3 |
| vol:0.5:4:0.1+opp:0.5:4:0.2 | 5,749 | 4.40 | 6.29 | 1,530 | -0.37 | 6.28 | 0.608 | 93.29 | 89.5 |
| vol:0.5:2:0.1 | 5,749 | 4.35 | 6.23 | 1,530 | -0.28 | 6.24 | 0.617 | 92.99 | 89.2 |

Starter-caliber = the top 12 QB, 30 RB, 36 WR and 12 TE by that model's own prediction each week (what a 12-team league starts). MAE (all) covers every player with a stat row, most of whom score under 5.

### Paired bootstrap (weeks resampled, 4000 draws)

- vol:0.5:4:0.1+opp:0.5:4:0.2 beat the naive baseline on lineup points: +1.30 per team-week, 95% interval +0.14 to +2.50 over 17 weeks; MAE -0.115 (-0.252 to -0.012).
- vol:0.5:4:0.1+opp:0.5:4:0.2 did NOT beat the engine's k=4 baseline half on lineup points: +0.20 per team-week, 95% interval -0.73 to +1.09 over 17 weeks; MAE -0.029 (-0.046 to -0.012).

### Gap to the noise floor closed (held-out season, players with 8+ games, MAE)

Naive, model and floor are all measured on the same players (8 or more games in 2025). Floor = the MAE a model would have if it knew each player's true 2025 weekly mean.

| Model | Pos | MAE | Naive MAE | Floor | Naive-to-floor gap | Gap closed | n |
|---|---|---|---|---|---|---|---|
| naive | DEF | 5.11 | 5.11 | 4.49 | 0.61 | 0.0% | 512 |
| naive | QB | 9.24 | 9.24 | 7.99 | 1.25 | 0.0% | 474 |
| naive | RB | 4.60 | 4.60 | 4.17 | 0.43 | 0.0% | 1,371 |
| naive | TE | 3.42 | 3.42 | 3.02 | 0.40 | 0.0% | 1,046 |
| naive | WR | 4.36 | 4.36 | 3.81 | 0.55 | 0.0% | 2,074 |
| kblend:4 | DEF | 4.85 | 5.11 | 4.49 | 0.61 | 41.7% | 512 |
| kblend:4 | QB | 8.76 | 9.24 | 7.99 | 1.25 | 38.3% | 474 |
| kblend:4 | RB | 4.57 | 4.60 | 4.17 | 0.43 | 7.9% | 1,371 |
| kblend:4 | TE | 3.35 | 3.42 | 3.02 | 0.40 | 16.0% | 1,046 |
| kblend:4 | WR | 4.21 | 4.36 | 3.81 | 0.55 | 26.9% | 2,074 |
| vol:0.5:4:0.1+opp:0.5:4:0.2 | DEF | 4.75 | 5.11 | 4.49 | 0.61 | 58.5% | 512 |
| vol:0.5:4:0.1+opp:0.5:4:0.2 | QB | 8.50 | 9.24 | 7.99 | 1.25 | 59.1% | 474 |
| vol:0.5:4:0.1+opp:0.5:4:0.2 | RB | 4.51 | 4.60 | 4.17 | 0.43 | 20.7% | 1,371 |
| vol:0.5:4:0.1+opp:0.5:4:0.2 | TE | 3.35 | 3.42 | 3.02 | 0.40 | 17.3% | 1,046 |
| vol:0.5:4:0.1+opp:0.5:4:0.2 | WR | 4.22 | 4.36 | 3.81 | 0.55 | 24.4% | 2,074 |
| vol:0.5:2:0.1 | DEF | 4.90 | 5.11 | 4.49 | 0.61 | 33.9% | 512 |
| vol:0.5:2:0.1 | QB | 8.55 | 9.24 | 7.99 | 1.25 | 54.7% | 474 |
| vol:0.5:2:0.1 | RB | 4.46 | 4.60 | 4.17 | 0.43 | 31.4% | 1,371 |
| vol:0.5:2:0.1 | TE | 3.29 | 3.42 | 3.02 | 0.40 | 31.6% | 1,046 |
| vol:0.5:2:0.1 | WR | 4.18 | 4.36 | 3.81 | 0.55 | 31.7% | 2,074 |

### Per-position paired bootstrap vs the engine's k=4 baseline half (held-out season, 8+ game players, weekly MAE difference; negative = better)

| Model | Pos | Mean diff | 95% low | 95% high | Weeks | Crosses zero |
|---|---|---|---|---|---|---|
| naive | QB | 0.429 | 0.059 | 0.980 | 17 | no |
| naive | RB | 0.036 | -0.073 | 0.152 | 17 | yes |
| naive | WR | 0.138 | 0.030 | 0.293 | 17 | no |
| naive | TE | 0.065 | -0.031 | 0.171 | 17 | yes |
| naive | DEF | 0.250 | 0.080 | 0.464 | 17 | no |
| vol:0.5:4:0.1+opp:0.5:4:0.2 | QB | -0.270 | -0.408 | -0.131 | 17 | no |
| vol:0.5:4:0.1+opp:0.5:4:0.2 | RB | -0.054 | -0.091 | -0.016 | 17 | no |
| vol:0.5:4:0.1+opp:0.5:4:0.2 | WR | 0.013 | -0.013 | 0.041 | 17 | yes |
| vol:0.5:4:0.1+opp:0.5:4:0.2 | TE | -0.006 | -0.042 | 0.032 | 17 | yes |
| vol:0.5:4:0.1+opp:0.5:4:0.2 | DEF | -0.100 | -0.170 | -0.024 | 17 | no |
| vol:0.5:2:0.1 | QB | -0.208 | -0.297 | -0.116 | 17 | no |
| vol:0.5:2:0.1 | RB | -0.101 | -0.149 | -0.050 | 17 | no |
| vol:0.5:2:0.1 | WR | -0.026 | -0.053 | 0.004 | 17 | yes |
| vol:0.5:2:0.1 | TE | -0.062 | -0.093 | -0.030 | 17 | no |
| vol:0.5:2:0.1 | DEF | 0.048 | 0.015 | 0.082 | 17 | no |

## Select block 2020-2024: all 36 configurations

| Model | n | MAE (all) | MAE (starters) | RMSE | Spearman | Lineup pts / team-week | % optimal |
|---|---|---|---|---|---|---|---|
| vol:0.5:4:0.1+opp:0.5:4:0.2 | 27,660 | 4.45 | 6.33 | 6.29 | 0.625 | 94.34 | 90.7 |
| vol:0.5:4:0.1+opp:1.0:4:0.2 | 27,660 | 4.49 | 6.40 | 6.35 | 0.620 | 94.33 | 90.6 |
| kblend:4+opp:0.5:4:0.2 | 27,660 | 4.46 | 6.38 | 6.32 | 0.621 | 94.19 | 90.5 |
| ewk:0.1:4+opp:0.5:4:0.2 | 27,660 | 4.46 | 6.40 | 6.31 | 0.624 | 94.18 | 90.5 |
| ewk:0.1:4+opp:1.0:4:0.2 | 27,660 | 4.49 | 6.49 | 6.36 | 0.619 | 94.18 | 90.5 |
| kblend:4+opp:1.0:4:0.2 | 27,660 | 4.50 | 6.48 | 6.38 | 0.617 | 94.17 | 90.5 |
| vol:0.5:2 | 27,660 | 4.43 | 6.34 | 6.27 | 0.632 | 94.15 | 90.5 |
| vol:1.0:4:0.1+opp:0.5:4:0.2 | 27,660 | 4.50 | 6.36 | 6.36 | 0.618 | 94.06 | 90.4 |
| vol:0.5:4 | 27,660 | 4.47 | 6.31 | 6.31 | 0.622 | 94.03 | 90.4 |
| vol:0.5:2:0.1 | 27,660 | 4.42 | 6.34 | 6.25 | 0.635 | 94.02 | 90.3 |
| ewk:0.1:4 | 27,660 | 4.46 | 6.38 | 6.31 | 0.624 | 94.02 | 90.3 |
| vol:0.5:4:0.1 | 27,660 | 4.46 | 6.33 | 6.29 | 0.625 | 94.01 | 90.3 |
| ewk:0.1:8 | 27,660 | 4.52 | 6.36 | 6.38 | 0.609 | 94.01 | 90.3 |
| vol:1.0:2:0.1 | 27,660 | 4.48 | 6.33 | 6.32 | 0.627 | 93.98 | 90.3 |
| kblend:6 | 27,660 | 4.50 | 6.36 | 6.36 | 0.614 | 93.97 | 90.3 |
| ewk:0.1:2 | 27,660 | 4.45 | 6.50 | 6.30 | 0.631 | 93.94 | 90.3 |
| kblend:4 | 27,660 | 4.47 | 6.38 | 6.32 | 0.621 | 93.91 | 90.2 |
| vol:1.0:4:0.1+opp:1.0:4:0.2 | 27,660 | 4.54 | 6.43 | 6.41 | 0.613 | 93.90 | 90.2 |
| vol:1.0:2 | 27,660 | 4.49 | 6.36 | 6.34 | 0.623 | 93.86 | 90.2 |
| vol:1.0:4:0.1 | 27,660 | 4.50 | 6.32 | 6.35 | 0.618 | 93.84 | 90.2 |
| kblend:8 | 27,660 | 4.53 | 6.34 | 6.40 | 0.607 | 93.83 | 90.2 |
| kblend:1 | 27,660 | 4.47 | 6.56 | 6.35 | 0.629 | 93.74 | 90.1 |
| kblend:2 | 27,660 | 4.45 | 6.45 | 6.31 | 0.628 | 93.73 | 90.1 |
| ewma:0.1 | 27,660 | 4.58 | 6.88 | 6.58 | 0.616 | 93.73 | 90.1 |
| ewma:0.2 | 27,660 | 4.60 | 6.96 | 6.61 | 0.615 | 93.66 | 90.0 |
| vol:1.0:4 | 27,660 | 4.51 | 6.32 | 6.37 | 0.615 | 93.64 | 90.0 |
| kblend:12 | 27,660 | 4.58 | 6.35 | 6.46 | 0.595 | 93.55 | 89.9 |
| naive | 27,660 | 4.58 | 6.86 | 6.59 | 0.614 | 93.55 | 89.9 |
| lastN:6 | 27,660 | 4.63 | 6.96 | 6.65 | 0.610 | 93.54 | 89.9 |
| ewma:0.3 | 27,660 | 4.64 | 7.05 | 6.67 | 0.612 | 93.54 | 89.9 |
| lastN:5 | 27,660 | 4.66 | 7.06 | 6.69 | 0.608 | 93.38 | 89.7 |
| lastN:4 | 27,660 | 4.70 | 7.16 | 6.76 | 0.603 | 93.37 | 89.7 |
| ewma:0.4 | 27,660 | 4.70 | 7.19 | 6.76 | 0.606 | 93.33 | 89.7 |
| ewma:0.5 | 27,660 | 4.78 | 7.38 | 6.88 | 0.598 | 93.21 | 89.6 |
| lastN:3 | 27,660 | 4.79 | 7.36 | 6.87 | 0.594 | 93.09 | 89.5 |
| lastN:2 | 27,660 | 4.97 | 7.71 | 7.15 | 0.574 | 92.38 | 88.8 |

### MAE by position, held-out season

| Model | QB | RB | WR | TE | DEF |
|---|---|---|---|---|---|
| naive | 8.72 (n=630) | 4.38 (n=1547) | 4.19 (n=2361) | 3.13 (n=1211) | 5.11 (n=512) |
| kblend:4 | 8.60 (n=630) | 4.36 (n=1547) | 4.04 (n=2361) | 3.09 (n=1211) | 4.85 (n=512) |
| vol:0.5:4:0.1+opp:0.5:4:0.2 | 8.43 (n=630) | 4.31 (n=1547) | 4.05 (n=2361) | 3.08 (n=1211) | 4.75 (n=512) |
| vol:0.5:2:0.1 | 8.39 (n=630) | 4.26 (n=1547) | 4.01 (n=2361) | 3.03 (n=1211) | 4.90 (n=512) |

### MAE by week of season, held-out season

| Week | naive | kblend:4 | vol:0.5:4:0.1+opp:0.5:4:0.2 | vol:0.5:2:0.1 |
|---|---|---|---|---|
| 2 | 5.60 (n=353) | 4.58 (n=353) | 4.61 (n=353) | 4.50 (n=353) |
| 3 | 4.78 (n=356) | 4.35 (n=356) | 4.33 (n=356) | 4.31 (n=356) |
| 4 | 4.51 (n=358) | 4.67 (n=358) | 4.67 (n=358) | 4.53 (n=358) |
| 5 | 4.15 (n=323) | 4.23 (n=323) | 4.27 (n=323) | 4.17 (n=323) |
| 6 | 4.59 (n=326) | 4.46 (n=326) | 4.41 (n=326) | 4.36 (n=326) |
| 7 | 4.61 (n=343) | 4.61 (n=343) | 4.59 (n=343) | 4.51 (n=343) |
| 8 | 4.60 (n=295) | 4.52 (n=295) | 4.50 (n=295) | 4.49 (n=295) |
| 9 | 4.39 (n=316) | 4.34 (n=316) | 4.30 (n=316) | 4.30 (n=316) |
| 10 | 4.46 (n=318) | 4.58 (n=318) | 4.51 (n=318) | 4.44 (n=318) |
| 11 | 4.36 (n=336) | 4.30 (n=336) | 4.26 (n=336) | 4.22 (n=336) |
| 12 | 4.33 (n=314) | 4.37 (n=314) | 4.33 (n=314) | 4.26 (n=314) |
| 13 | 4.16 (n=352) | 4.12 (n=352) | 4.11 (n=352) | 4.04 (n=352) |
| 14 | 4.36 (n=329) | 4.40 (n=329) | 4.35 (n=329) | 4.39 (n=329) |
| 15 | 4.72 (n=350) | 4.61 (n=350) | 4.53 (n=350) | 4.54 (n=350) |
| 16 | 4.47 (n=365) | 4.50 (n=365) | 4.51 (n=365) | 4.48 (n=365) |
| 17 | 4.29 (n=359) | 4.28 (n=359) | 4.21 (n=359) | 4.19 (n=359) |
| 18 | 4.28 (n=356) | 4.29 (n=356) | 4.22 (n=356) | 4.24 (n=356) |

### MAE by season, select block (naive vs selected)

| Season | naive | vol:0.5:4:0.1+opp:0.5:4:0.2 |
|---|---|---|
| 2020 | 4.86 (n=5,313) | 4.68 (n=5,313) |
| 2021 | 4.68 (n=5,634) | 4.52 (n=5,634) |
| 2022 | 4.53 (n=5,571) | 4.36 (n=5,571) |
| 2023 | 4.43 (n=5,551) | 4.34 (n=5,551) |
| 2024 | 4.43 (n=5,591) | 4.36 (n=5,591) |

## B6.1 Split-half reliability (odd vs even weeks, Spearman-Brown corrected; players with 10+ games; 2015-2024)

| Stat | Pos | r (corrected) | r (half) | Player-seasons | Seasons | r by season (min to max) |
|---|---|---|---|---|---|---|
| carry_share | RB | 0.976 | 0.952 | 895 | 10 | 0.92 to 0.96 |
| carries_pg | RB | 0.963 | 0.930 | 895 | 10 | 0.88 to 0.95 |
| target_share | WR | 0.952 | 0.908 | 1339 | 10 | 0.87 to 0.93 |
| target_share | TE | 0.948 | 0.902 | 641 | 10 | 0.89 to 0.92 |
| targets_pg | TE | 0.943 | 0.892 | 641 | 10 | 0.86 to 0.93 |
| targets_pg | WR | 0.942 | 0.891 | 1339 | 10 | 0.87 to 0.92 |
| air_yards_share | WR | 0.932 | 0.872 | 1339 | 10 | 0.85 to 0.89 |
| carries_pg | QB | 0.928 | 0.866 | 307 | 10 | 0.84 to 0.92 |
| target_share | RB | 0.919 | 0.850 | 895 | 10 | 0.74 to 0.90 |
| targets_pg | RB | 0.913 | 0.840 | 895 | 10 | 0.71 to 0.89 |
| air_yards_share | TE | 0.908 | 0.831 | 641 | 10 | 0.79 to 0.86 |
| ppg | RB | 0.903 | 0.823 | 895 | 10 | 0.73 to 0.88 |
| ppg | TE | 0.873 | 0.774 | 641 | 10 | 0.65 to 0.83 |
| rz_touches_pg | RB | 0.868 | 0.767 | 895 | 10 | 0.68 to 0.84 |
| ppg | WR | 0.857 | 0.750 | 1339 | 10 | 0.68 to 0.80 |
| pass_att_pg | QB | 0.828 | 0.706 | 307 | 10 | 0.40 to 0.92 |
| ppg | QB | 0.736 | 0.583 | 307 | 10 | 0.38 to 0.82 |
| rz_touches_pg | TE | 0.732 | 0.577 | 641 | 10 | 0.36 to 0.71 |
| rz_touches_pg | WR | 0.696 | 0.533 | 1339 | 10 | 0.44 to 0.62 |
| yards_per_touch | RB | 0.478 | 0.314 | 830 | 10 | 0.15 to 0.49 |
| yards_per_touch | WR | 0.477 | 0.313 | 1199 | 10 | 0.19 to 0.45 |
| yards_per_touch | TE | 0.419 | 0.265 | 584 | 10 | 0.07 to 0.41 |
| td_rate | TE | 0.220 | 0.124 | 584 | 10 | -0.15 to 0.27 |
| td_rate | WR | 0.182 | 0.100 | 1199 | 10 | -0.07 to 0.28 |
| td_rate | RB | 0.101 | 0.053 | 830 | 10 | -0.15 to 0.31 |

## B6.2 Persistence (autocorrelation by lag, best simple window and best decay for predicting the next game; 8+ games)

| Stat | Pos | lag1 | lag2 | lag3 | lag4 | lag5 | lag6 | n (lag 1) | Best window | Best decay |
|---|---|---|---|---|---|---|---|---|---|---|
| ppg | QB | 0.237 | 0.192 | 0.192 | 0.173 | 0.195 | 0.173 | 4,495 | 8 | 0.1 |
| ppg | RB | 0.456 | 0.430 | 0.399 | 0.381 | 0.381 | 0.374 | 12,823 | 8 | 0.1 |
| ppg | WR | 0.327 | 0.325 | 0.318 | 0.310 | 0.309 | 0.303 | 19,024 | 8 | 0.1 |
| ppg | TE | 0.327 | 0.308 | 0.319 | 0.325 | 0.302 | 0.267 | 9,013 | 8 | 0.1 |
| targets_pg | RB | 0.461 | 0.447 | 0.424 | 0.415 | 0.399 | 0.381 | 12,823 | 8 | 0.1 |
| targets_pg | WR | 0.565 | 0.541 | 0.527 | 0.521 | 0.510 | 0.506 | 19,024 | 8 | 0.2 |
| targets_pg | TE | 0.536 | 0.503 | 0.501 | 0.492 | 0.482 | 0.454 | 9,013 | 8 | 0.1 |
| target_share | RB | 0.471 | 0.461 | 0.437 | 0.439 | 0.419 | 0.402 | 12,823 | 8 | 0.1 |
| target_share | WR | 0.607 | 0.587 | 0.573 | 0.563 | 0.552 | 0.551 | 19,024 | 6 | 0.2 |
| target_share | TE | 0.567 | 0.553 | 0.538 | 0.527 | 0.513 | 0.497 | 9,013 | 8 | 0.1 |
| carries_pg | RB | 0.697 | 0.654 | 0.629 | 0.596 | 0.582 | 0.572 | 12,823 | 6 | 0.3 |
| carries_pg | QB | 0.512 | 0.504 | 0.477 | 0.493 | 0.474 | 0.479 | 4,495 | 8 | 0.1 |
| carry_share | RB | 0.789 | 0.740 | 0.711 | 0.683 | 0.665 | 0.653 | 12,823 | 3 | 0.4 |
| rz_touches_pg | RB | 0.368 | 0.324 | 0.307 | 0.285 | 0.297 | 0.282 | 12,823 | 8 | 0.1 |
| rz_touches_pg | WR | 0.179 | 0.166 | 0.162 | 0.155 | 0.164 | 0.166 | 19,024 | 8 | 0.1 |
| rz_touches_pg | TE | 0.181 | 0.151 | 0.159 | 0.171 | 0.145 | 0.143 | 9,013 | 8 | 0.1 |
| yards_per_touch | RB | 0.113 | 0.127 | 0.093 | 0.096 | 0.100 | 0.104 | 12,823 | 8 | 0.1 |
| yards_per_touch | WR | 0.191 | 0.170 | 0.163 | 0.167 | 0.153 | 0.159 | 19,024 | 8 | 0.1 |
| yards_per_touch | TE | 0.118 | 0.109 | 0.098 | 0.108 | 0.106 | 0.090 | 9,013 | 8 | 0.1 |
| td_rate | RB | 0.032 | 0.011 | 0.026 | 0.011 | 0.010 | 0.025 | 12,823 | 6 | 0.1 |
| td_rate | WR | 0.037 | 0.039 | 0.029 | 0.038 | 0.046 | 0.032 | 19,024 | 8 | 0.1 |
| td_rate | TE | 0.005 | 0.009 | 0.018 | 0.021 | 0.005 | -0.003 | 9,013 | 8 | 0.1 |
| air_yards_share | WR | 0.511 | 0.493 | 0.492 | 0.486 | 0.472 | 0.469 | 19,024 | 8 | 0.1 |
| air_yards_share | TE | 0.459 | 0.445 | 0.433 | 0.419 | 0.422 | 0.418 | 9,013 | 8 | 0.1 |
| pass_att_pg | QB | 0.354 | 0.311 | 0.287 | 0.267 | 0.227 | 0.223 | 4,495 | 8 | 0.2 |

Decay used by the recency models (median of the ppg best-decay across positions on the fit block): 0.1.

## B6.3 Noise floor (players with 8+ games, 2015-2024)

| Pos | Player-seasons | Player-weeks | Total var | Between-player var | Within-player var | Share predictable | Floor MAE (known mean) | Floor RMSE |
|---|---|---|---|---|---|---|---|---|
| QB | 352 | 4,847 | 115.5 | 32.68 | 86.15 | 0.283 | 7.413 | 9.282 |
| RB | 1068 | 13,891 | 59.0 | 25.85 | 32.99 | 0.438 | 4.124 | 5.744 |
| WR | 1541 | 20,565 | 50.84 | 18.13 | 32.43 | 0.357 | 4.151 | 5.695 |
| TE | 777 | 9,790 | 29.6 | 10.18 | 19.08 | 0.344 | 3.121 | 4.368 |
| DEF | 320 | 5,246 | 38.73 | 4.25 | 34.51 | 0.110 | 4.576 | 5.874 |

## B6.4 Calibration on the held-out season

### naive: slope of actual on predicted = 0.784 (intercept 1.68, r = 0.594, n = 5,749)

| Decile | n | Mean predicted | Mean actual |
|---|---|---|---|
| 1 | 574 | 0.33 | 1.92 |
| 2 | 575 | 1.59 | 2.67 |
| 3 | 575 | 2.68 | 3.81 |
| 4 | 575 | 3.59 | 4.41 |
| 5 | 575 | 4.63 | 4.81 |
| 6 | 575 | 6.1 | 6.43 |
| 7 | 575 | 8.07 | 8.62 |
| 8 | 575 | 10.25 | 9.92 |
| 9 | 575 | 13.4 | 12.02 |
| 10 | 575 | 20.71 | 18.13 |

### kblend:4: slope of actual on predicted = 0.887 (intercept 0.93, r = 0.615, n = 5,749)

| Decile | n | Mean predicted | Mean actual |
|---|---|---|---|
| 1 | 574 | 1.07 | 1.58 |
| 2 | 575 | 2.17 | 2.74 |
| 3 | 575 | 2.93 | 3.67 |
| 4 | 575 | 3.74 | 4.52 |
| 5 | 575 | 4.79 | 5.28 |
| 6 | 575 | 6.06 | 6.25 |
| 7 | 575 | 8.07 | 8.2 |
| 8 | 575 | 10.12 | 9.98 |
| 9 | 575 | 12.92 | 11.82 |
| 10 | 575 | 19.55 | 18.69 |

### vol:0.5:4:0.1+opp:0.5:4:0.2: slope of actual on predicted = 0.922 (intercept 0.78, r = 0.622, n = 5,749)

| Decile | n | Mean predicted | Mean actual |
|---|---|---|---|
| 1 | 574 | 1.11 | 1.48 |
| 2 | 575 | 2.15 | 2.86 |
| 3 | 575 | 2.77 | 3.48 |
| 4 | 575 | 3.63 | 4.67 |
| 5 | 575 | 4.76 | 5.22 |
| 6 | 575 | 6.12 | 6.41 |
| 7 | 575 | 7.97 | 8.21 |
| 8 | 575 | 10.08 | 9.53 |
| 9 | 575 | 12.96 | 12.05 |
| 10 | 575 | 18.91 | 18.82 |

### vol:0.5:2:0.1: slope of actual on predicted = 0.924 (intercept 0.74, r = 0.628, n = 5,749)

| Decile | n | Mean predicted | Mean actual |
|---|---|---|---|
| 1 | 574 | 1.06 | 1.44 |
| 2 | 575 | 2.11 | 2.87 |
| 3 | 575 | 2.78 | 3.49 |
| 4 | 575 | 3.62 | 4.24 |
| 5 | 575 | 4.8 | 5.28 |
| 6 | 575 | 6.24 | 6.18 |
| 7 | 575 | 8.01 | 8.44 |
| 8 | 575 | 10.04 | 9.84 |
| 9 | 575 | 13.03 | 12.21 |
| 10 | 575 | 19.05 | 18.73 |

### 80% prediction intervals for vol:0.5:4:0.1+opp:0.5:4:0.2 (residual quantiles fitted on 2020-2024, coverage tested on 2025)

| Pos | Projection level | Low | High | Width | n test | Coverage |
|---|---|---|---|---|---|---|
| QB | 15 to 20 | -13.5 | +13.3 | 26.8 | 223 | 0.771 |
| QB | 20 plus | -13.6 | +14.1 | 27.7 | 161 | 0.801 |
| QB | 10 to 15 | -13.0 | +11.8 | 24.9 | 167 | 0.790 |
| QB | 5 to 10 | -9.2 | +13.8 | 23.0 | 52 | 0.712 |
| QB | under 5 | -4.1 | +14.8 | 18.9 | 27 | 0.778 |
| RB | 5 to 10 | -6.0 | +9.8 | 15.9 | 421 | 0.822 |
| RB | 10 to 15 | -8.9 | +10.3 | 19.1 | 249 | 0.839 |
| RB | under 5 | -2.9 | +5.8 | 8.7 | 742 | 0.817 |
| RB | 20 plus | -13.7 | +15.3 | 29.0 | 11 | 0.818 |
| RB | 15 to 20 | -10.8 | +11.1 | 21.8 | 124 | 0.750 |
| WR | 5 to 10 | -6.0 | +8.8 | 14.9 | 748 | 0.795 |
| WR | under 5 | -3.4 | +5.6 | 9.0 | 1152 | 0.820 |
| WR | 10 to 15 | -8.7 | +10.9 | 19.7 | 401 | 0.825 |
| WR | 15 to 20 | -11.7 | +12.2 | 23.9 | 59 | 0.814 |
| TE | 5 to 10 | -5.6 | +7.5 | 13.1 | 382 | 0.772 |
| TE | under 5 | -2.8 | +4.9 | 7.7 | 775 | 0.822 |
| TE | 10 to 15 | -8.9 | +9.4 | 18.3 | 51 | 0.745 |
| DEF | 5 to 10 | -6.6 | +8.6 | 15.2 | 396 | 0.801 |
| DEF | 10 to 15 | -8.5 | +7.0 | 15.5 | 99 | 0.778 |
| DEF | under 5 | -4.1 | +7.9 | 12.0 | 16 | 0.562 |

## B6.6 Where lineup points leak (select block, manager rule: naive (start by season average to date; prior-season ppg in week 1); 1,008 team-weeks)

Total gap to the hindsight-optimal lineup: 10.52 points per team-week.

| Slot | Gap / week | Share |
|---|---|---|
| QB | 2.29 | 21.8% |
| RB | 1.41 | 13.5% |
| WR | 1.54 | 14.6% |
| TE | 2.57 | 24.4% |
| DEF | 2.7 | 25.7% |

FLEX view (same team-weeks): the five skill starters split into the RB/WR core (best two RB and best two WR actually started) and the FLEX picks (everything else, including any TE).

| Slot group | Gap / week | Share |
|---|---|---|
| QB | 2.29 | 21.8% |
| RB/WR core | 2.24 | 21.3% |
| FLEX picks | 3.28 | 31.2% |
| DEF | 2.7 | 25.7% |

## B6.7 Role-change detection (share jump vs points jump; 2015-2024)

| Share stat | Positions | Jump | Share events | Sustained | False positive rate | With points event | Mean lead (weeks) | Share first | Same week |
|---|---|---|---|---|---|---|---|---|---|
| tgt_share_calc | WR/TE | 0.08 | 758 | 213 | 0.719 | 177 | 0.93 | 0.435 | 0.565 |
| car_share | RB | 0.15 | 374 | 175 | 0.532 | 149 | 0.81 | 0.396 | 0.604 |
| tgt_share_calc | RB | 0.06 | 360 | 88 | 0.756 | 74 | 0.64 | 0.351 | 0.649 |

## Tests

- Leakage test: season 2025, weeks after 9 corrupted; 32 week x model pairs checked, 0 changed; control week differs: True. **PASSED**
- Determinism test: two identical runs on the held-out season produced identical output (5,964 bytes). **PASSED**

## Limitations

- No archive of Sleeper's weekly projections exists, so this harness cannot tune w, the weight on Sleeper's number in the live blend; it tunes only the baseline half that Sleeper is blended against.
- Rosters in the lineup simulation are fixed for the season (drafted from prior-season points per game); no waivers or trades, and rookies with no prior season are not drafted.
- Only players with a stat row in a week are eligible for that week's lineup, which is how Sleeper treats ruled-out players but assumes the manager knew every inactive in advance.
- Week 1 is not evaluated (no in-season data); every model falls back to the prior-season number there.
- Injury status, weather, Vegas totals and depth-chart news are not in the data.

## Volume coefficients (fit block)

| Pos | Intercept | targets | carries | red-zone touches | pass attempts |
|---|---|---|---|---|---|
| QB | 0.535 | -0.313 | 0.834 | 1.212 | 0.454 |
| WR | 0.721 | 1.208 | 0.765 | 0.942 | 1.732 |
| TE | 0.032 | 1.202 | 0.632 | 1.185 | -0.357 |
| RB | 0.214 | 0.993 | 0.475 | 0.921 | 2.087 |

<!-- vacated-share backtest -->

## Vacated target share (display-only column)

Generated 2026-09-20T21:40:34Z. Select block 2015-2024, held out 2025. Expected points for the pairing come from `kblend:4`, the engine's own baseline half, and a pair counts as close when it is within 1.5 points.

### Data

nflverse `injuries` release: present for 2014 to 2026 (13 seasons). Rows carry `report_status` and `practice_status`; weeks 1 to 18 of each season plus the playoffs, which are filtered out. A player counts as absent when that week's report says Out or Doubtful, or when he was absent the week before and had no stat row that week.

| Season | Injury rows | Weeks | Rows with a report status | Rows marked Out |
|---|---|---|---|---|
| 2014 | 5,078 | 21 | 4,855 | 913 |
| 2015 | 5,232 | 21 | 5,079 | 979 |
| 2016 | 5,115 | 21 | 3,079 | 1,043 |
| 2017 | 5,104 | 21 | 2,585 | 897 |
| 2018 | 5,133 | 21 | 2,430 | 920 |
| 2019 | 5,392 | 21 | 2,534 | 1,036 |
| 2020 | 5,661 | 21 | 2,535 | 901 |
| 2021 | 5,587 | 22 | 2,567 | 888 |
| 2022 | 5,682 | 22 | 2,745 | 1,078 |
| 2023 | 5,599 | 19 | 2,721 | 996 |
| 2024 | 6,215 | 22 | 2,829 | 1,116 |
| 2025 | 6,068 | 22 | 2,785 | 1,382 |
| 2026 | 433 | 2 | 166 | 75 |

### Select block 2015-2024

164 season-weeks, 12 simulated rosters each. The two tiebreaks chose different lineups in 681 team-weeks.

| Arm | Lineup pts / team-week | Starters swapped in vs no tiebreak |
|---|---|---|
| none | 93.966 | 0 |
| boom | 93.542 | 687 |
| vacated:proportional | 93.945 | 249 |
| vacated:historical | 93.965 | 226 |

Paired bootstrap over weeks (positive = the first arm scored more):

| Comparison | Mean diff | Crosses zero |
|---|---|---|
| vacated:proportional vs boom | +0.402 (+0.081 to +0.730, 164 weeks) | no |
| vacated:historical vs boom | +0.423 (+0.119 to +0.736, 164 weeks) | no |
| boom vs none | -0.423 (-0.706 to -0.144, 164 weeks) | no |
| vacated:proportional vs none | -0.021 (-0.186 to +0.139, 164 weeks) | yes |
| vacated:historical vs none | -0.001 (-0.159 to +0.158, 164 weeks) | yes |

Estimator carried to the held-out season: **vacated:historical**.

### Held-out season 2025

17 weeks, touched once.

| Arm | Lineup pts / team-week | Starters swapped in vs no tiebreak |
|---|---|---|
| none | 93.090 | 0 |
| boom | 93.049 | 71 |
| vacated:historical | 92.861 | 11 |

| Comparison | Mean diff | Crosses zero |
|---|---|---|
| vacated:historical vs boom | -0.188 (-0.888 to +0.552, 17 weeks) | yes |
| vacated:historical vs none | -0.229 (-0.418 to -0.064, 17 weeks) | no |
| boom vs none | -0.041 (-0.700 to +0.582, 17 weeks) | yes |

### Verdict

- NULL RESULT. On held-out 2025 the vacated tiebreak did not beat the boom-rate tiebreak: -0.188 (-0.888 to +0.552, 17 weeks) lineup points per team-week, and the interval includes zero. The column therefore ships as information only and the close-call tiebreak stays on boom rate.
- Against no tiebreak at all, the vacated arm scored -0.229 (-0.418 to -0.064, 17 weeks) on held-out 2025, which is measurably worse: swapping on this signal inside the close-call window costs points. That is another reason it stays a display column.
- For scale, the tiebreak the engine uses today scored -0.041 (-0.700 to +0.582, 17 weeks) against no tiebreak on held-out 2025. On the select block it was -0.423 (-0.706 to -0.144, 164 weeks), i.e. the boom-rate rule is not itself established as an improvement; nothing here promotes it either.
- Estimators: proportional and historical. The select block preferred historical, by 0.020 lineup points per team-week, which is well inside the noise; treat the choice between them as arbitrary.
- The column never enters `expected` in any arm. tests/test_vacated.py asserts that a roster's expected points are identical with the column computed and with it absent.

### Limitations

- Expected points are the engine's k=4 baseline half, not the live 0.65 Sleeper blend; no archive of Sleeper's weekly projections exists.
- Absence is read from the nflverse weekly injury report (Out or Doubtful) plus a carry-forward for players who drop off the report; a healthy scratch who never appears on the report is counted as available, which understates vacated share.
- Vacated share counts absent teammates at the same position only. Cross-position flow (a TE's targets going to WRs) is not modeled.
- Boom rate here is computed from the previous season, because the preseason model's boom_rate column is a 2026 artifact with no historical equivalent.
- Rosters are the main harness's fixed drafted rosters; no waivers, no trades.

