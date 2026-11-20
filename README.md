# Nasdaq-100 · Pay & Pray

[Otevřít tržní přehled](https://michalmachalik.github.io/Nasdaq100-PAYandPRAY/)

Český dashboard pro sledování futures na Nasdaq-100, největších firem indexu a makroekonomických ukazatelů. Stránka načítá zveřejněné soubory JSON. U kotací zobrazuje čas zdroje nebo čas načtení podle toho, co poskytovatel zpřístupňuje.

## Odkud pocházejí data

| Soubor v `data/` | Obsah a způsob aktualizace |
| --- | --- |
| `futures.json`, `futures-ath.json` | Kotace kontraktu NQ=F a historické maximum kontinuální řady z Yahoo Finance. Samostatné úlohy kontrolují kotaci ve všední dny a historii denně. |
| `ndx-constituents.json`, `top10.json` | Členství v indexu podle Nasdaq a deset firem podle tržní kapitalizace z CompaniesMarketCap. Pořadí vyjadřuje velikost firmy, váha v indexu se z něj přímo určit nedá. |
| `markets.json` | Komodity a měnové páry s datem zdrojové kotace z Trading Economics. |
| `economy.json`, `latest.json` | Sazby centrálních bank, meziroční změny HDP a obsah aktuálního reportu. Mají vlastní referenční období. |

Tlačítko **Obnovit stránku a data** načte poslední publikovaný přehled. Aktualizaci souborů řídí [naplánované úlohy](.github/workflows/). Pokud poskytovatel vynechá intradenní svíčky, skript přijme jeho cenu pouze s odpovídajícím časem kotace a uplatní stejnou kontrolu stáří. Při výpadku seznamu Nasdaq lze použít poslední ověřené složení indexu staré nejvýše sedm dní. Původní datum členství zůstává v reportu.

## Lokální spuštění

Z kořene repozitáře spusťte statický server a otevřete [localhost na portu 8000](http://127.0.0.1:8000/).

```sh
python -m http.server 8000 --bind 127.0.0.1
```

## Kontrola před publikací

Validace vyžaduje Python 3, Beautiful Soup a Node.js. Zkontroluje cílové HTML prvky, období HDP i syntaxi JavaScriptu. Poté vykreslí skutečný obsah `data/latest.json` v testovacím prostředí.

```sh
python -m pip install beautifulsoup4 tzdata
python scripts/prepare_site.py
python -m unittest discover -s tests
```

[Zdrojové skripty](scripts/) · [Datové soubory](data/) · [Licence MIT](LICENSE)
