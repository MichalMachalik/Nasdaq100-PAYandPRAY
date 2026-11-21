# Nasdaq-100 · Pay & Pray

[Otevřít tržní přehled](https://michalmachalik.github.io/Nasdaq100-PAYandPRAY/)

Český dashboard pro sledování futures na Nasdaq-100, největších firem indexu a makroekonomických ukazatelů. Stránka načítá zveřejněné soubory JSON. U kotací zobrazuje čas zdroje nebo čas načtení podle toho, co poskytovatel zpřístupňuje.

## Odkud pocházejí data

| Soubor v `data/` | Obsah a způsob aktualizace |
| --- | --- |
| `futures.json`, `futures-ath.json` | Kotace kontraktu NQ=F a historické maximum kontinuální řady z Yahoo Finance. Kotace se kontroluje každých pět minut, historické maximum každou hodinu; obě úlohy běží každý den včetně víkendů a svátků. |
| `ndx-constituents.json`, `top10.json` | Členství v indexu podle Nasdaq a deset firem podle tržní kapitalizace z CompaniesMarketCap. Pořadí vyjadřuje velikost firmy, váha v indexu se z něj přímo určit nedá. |
| `markets.json` | Komodity a měnové páry s datem zdrojové kotace z Trading Economics. |
| `economy.json`, `latest.json` | Sazby centrálních bank, meziroční změny HDP a obsah aktuálního reportu. Mají vlastní referenční období. |

Tlačítko **Obnovit stránku a data** načte poslední publikovaný přehled. Aktualizaci souborů řídí [naplánované úlohy](.github/workflows/). Pokud poskytovatel vynechá intradenní svíčky, skript přijme jeho cenu pouze s odpovídajícím časem kotace a porovná čas této ceny s časem poslední intradenní svíčky. Při zavřeném trhu zůstává skutečný čas poslední kotace; údaj starší než 24 hodin je viditelně označený a čas úspěšné kontroly se ukládá zvlášť. Při výpadku seznamu Nasdaq lze použít poslední ověřené složení indexu staré nejvýše sedm dní. Původní datum členství zůstává v reportu.

Samostatné kontroly Top 10, komodit a FX, RSI, šířky trhu a vstupů VXN/Treasury běží každou hodinu 24/7. Denní indikátory používají skutečné datum pozorování; nezměněná úspěšná kontrola aktualizuje pouze `checkedAtUtc` (u jednotlivých rizikových zdrojů vlastní kontrolní čas). Nová zpráva ani obchodní den se tím nevytváří. Obsah `latest.json` a makroekonomické reference kontroluje navazující hodinový reporting.

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

