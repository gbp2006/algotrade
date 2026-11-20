# Контроли пробоя канала

instrument period       variant  trades    net   PF      DD
       CNY  train  control-long     664  -2135 0.90   -4179
       CNY  train channel-01-13     169   2920 2.07    -415
       CNY  train channel-13-13     193   2358 1.49    -986
       CNY    oos  control-long     226   -143 0.98    -801
       CNY    oos channel-01-13      47    715 2.17    -130
       CNY    oos channel-13-13      62    409 1.23    -495
        Si  train  control-long     759  17727 1.10  -17642
        Si  train channel-01-13     181  12385 1.44   -4682
        Si  train channel-13-13     196   9965 1.23   -9353
        Si    oos  control-long     212   1652 1.04   -6274
        Si    oos channel-01-13      47   4869 2.06   -1157
        Si    oos channel-13-13      54   1438 1.11   -3149
       RTS    oos  control-long     228 -22322 0.88  -78993
       RTS    oos channel-01-13      50   1124 1.04   -5696
       RTS    oos channel-13-13      53 -11354 0.71  -12964
      GOLD    oos  control-long     228 -38963 0.92 -107744
      GOLD    oos channel-01-13      77  15530 1.13  -51281
      GOLD    oos channel-13-13      45  20562 1.27  -39943
        BR    oos  control-long     224  29490 1.21  -22301
        BR    oos channel-01-13      78  12891 1.32  -10974
        BR    oos channel-13-13      58   5541 1.19  -11970

`control-long` — постоянный лонг в том же окне; `channel-01-13` — лучший из сетки; `channel-13-13` — граница равна времени решения, чтобы не вводить утренний таймер на WSL.
