# Nasdaq-100 · Pay & Pray

[Česká verze](#cesky)

[Open the market dashboard](https://michalmachalik.github.io/Nasdaq100-PAYandPRAY/)

A Czech-language dashboard with automated 24/7 checks for Nasdaq-100 futures, the index's largest companies and market indicators. The site reads published JSON files. Each quote shows either the source timestamp or the retrieval time, depending on what the provider supplies.

## Data sources and update schedule

| File in `data/` | Contents and updates |
| --- | --- |
| `futures.json`, `futures-ath.json` | NQ=F futures quotes and the all-time high of the continuous series from Yahoo Finance. The quote is checked every five minutes and the high every hour, including weekends and holidays. |
| `ndx-constituents.json`, `top10.json` | Nasdaq provides index membership. CompaniesMarketCap supplies market capitalizations for ranking the ten largest companies. A company's rank by size does not determine its index weight. |
| `markets.json` | Commodity and currency-pair quotes from Trading Economics, with source dates. |
| `economy.json`, `latest.json` | Central bank rates, year-on-year GDP changes and the current report, each with its own reference period. |

**Obnovit stránku a data** reloads the latest published snapshot. [Scheduled workflows](.github/workflows/) update the files. When a provider omits intraday candles, the script accepts a price only with a matching quote timestamp and compares it with the timestamp of the latest intraday candle. When the market is closed, the dashboard retains the actual time of the last quote. Quotes older than 24 hours are flagged, and the time of the last successful check is stored separately. If the Nasdaq membership list is unavailable, the report can reuse a verified list up to seven days old with its original membership date.

Separate checks for the top ten, commodities and FX, RSI, market breadth and VXN/Treasury inputs run hourly around the clock. Daily indicators retain the actual observation date. A successful check with unchanged data updates only `checkedAtUtc` or the individual risk source's check timestamp. It does not create a new report or trading day. A downstream hourly reporting job checks `latest.json` and the macroeconomic references.

## Run locally

Start a static server from the repository root and open [localhost on port 8000](http://127.0.0.1:8000/).

```sh
python -m http.server 8000 --bind 127.0.0.1
```

## Validate before publishing

Validation requires Python 3, Beautiful Soup and Node.js. It checks target HTML elements, GDP reference periods and JavaScript syntax, then renders the actual contents of `data/latest.json` in the test environment.

```sh
python -m pip install beautifulsoup4 tzdata
python scripts/prepare_site.py
python -m unittest discover -s tests
```

[Source scripts](scripts/) · [Data files](data/) · [MIT license](LICENSE)

---

<a name="cesky"></a>

## Česká verze

[Otevřít tržní přehled](https://michalmachalik.github.io/Nasdaq100-PAYandPRAY/)

Český dashboard pro sledování futures na Nasdaq-100, největších firem indexu a makroekonomických ukazatelů. Stránka načítá zveřejněné soubory JSON. U kotací zobrazuje čas zdroje nebo čas načtení podle toho, co poskytovatel zpřístupňuje.

### Odkud pocházejí data

| Soubor v `data/` | Obsah a způsob aktualizace |
| --- | --- |
| `futures.json`, `futures-ath.json` | Kotace kontraktu NQ=F a historické maximum kontinuální řady z Yahoo Finance. Kotace se kontroluje každých pět minut, historické maximum každou hodinu; obě úlohy běží každý den včetně víkendů a svátků. |
| `ndx-constituents.json`, `top10.json` | Členství v indexu podle Nasdaq a deset firem podle tržní kapitalizace z CompaniesMarketCap. Pořadí vyjadřuje velikost firmy, váha v indexu se z něj přímo určit nedá. |
| `markets.json` | Komodity a měnové páry s datem zdrojové kotace z Trading Economics. |
| `economy.json`, `latest.json` | Sazby centrálních bank, meziroční změny HDP a obsah aktuálního reportu. Mají vlastní referenční období. |

Tlačítko **Obnovit stránku a data** načte poslední publikovaný přehled. Aktualizaci souborů řídí [naplánované úlohy](.github/workflows/). Pokud poskytovatel vynechá intradenní svíčky, skript přijme jeho cenu pouze s odpovídajícím časem kotace a porovná čas této ceny s časem poslední intradenní svíčky. Při zavřeném trhu zůstává skutečný čas poslední kotace; údaj starší než 24 hodin je viditelně označený a čas úspěšné kontroly se ukládá zvlášť. Při výpadku seznamu Nasdaq lze použít poslední ověřené složení indexu staré nejvýše sedm dní. Původní datum členství zůstává v reportu.

Samostatné kontroly Top 10, komodit a FX, RSI, šířky trhu a vstupů VXN/Treasury běží každou hodinu 24/7. Denní indikátory používají skutečné datum pozorování; nezměněná úspěšná kontrola aktualizuje pouze `checkedAtUtc` (u jednotlivých rizikových zdrojů vlastní kontrolní čas). Nová zpráva ani obchodní den se tím nevytváří. Obsah `latest.json` a makroekonomické reference kontroluje navazující hodinový reporting.

### Lokální spuštění

Z kořene repozitáře spusťte statický server a otevřete [localhost na portu 8000](http://127.0.0.1:8000/).

```sh
python -m http.server 8000 --bind 127.0.0.1
```

### Kontrola před publikací

Validace vyžaduje Python 3, Beautiful Soup a Node.js. Zkontroluje cílové HTML prvky, období HDP i syntaxi JavaScriptu. Poté vykreslí skutečný obsah `data/latest.json` v testovacím prostředí.

```sh
python -m pip install beautifulsoup4 tzdata
python scripts/prepare_site.py
python -m unittest discover -s tests
```

[Zdrojové skripty](scripts/) · [Datové soubory](data/) · [Licence MIT](LICENSE)
