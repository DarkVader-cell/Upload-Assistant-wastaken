# Streaming-service codes

`src/region.py` maps release-name service labels to the uppercase codes used by
tracker integrations. The mapping accepts both canonical codes and common
service names. Indian and South Asian services currently include:

| Code | Recognized names |
| --- | --- |
| `AMZN` | Prime Video, Amazon Prime Video |
| `SNXT` | Sun NXT, SunNXT |
| `TK` | Tentkotta |
| `SONY` | Sony, Sony LIV, SonyLIV |
| `GPLAY` | Google Play, GooglePlay |
| `VOOT` | Voot, Voot Select |
| `DSPH` | Disney Plus Hotstar, Disney+ Hotstar, DisneyPlusHotstar |
| `JHS` | JioHotstar, Jio Hotstar |
| `ZEE5` | Zee5, ZEE 5 |
| `JC` | Jio Cinema, JioCinema |
| `SS` | Simply South, SimplySouth |
| `AHA` | Aha |
| `MX` | MX Player, MXPlayer |
| `HPLAY` | Hungama Play, HungamaPlay, Hungama |
| `TVF` | TVF Play, TVFPlay |
| `SME` | Shemaroo Me, ShemarooMe |
| `ALT` | ALT Balaji, AltBalaji |
| `LGP` | Lionsgate Play, LionsgatePlay |
| `BMS` | Book My Show, BookMyShow |
| `CHTV` | Chaupal TV, Chaupal, ChaupalTV |
| `MMAX` | ManoramaMAX, Manorama MAX, ManoramaMax |
| `SPLAY` | Sainaplay, Saina Play, SainaPlay |
| `DSCV` | Discovery+ |
| `CRKI` | Chorki, chorki |

Service codes are uppercase except for the established conventional codes
`iP`, `iT`, and `iQIYI`. SonyLIV is also detected when a filename joins it to
other tokens with punctuation, underscores, or no separator.
