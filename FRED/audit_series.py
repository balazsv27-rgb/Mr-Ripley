"""Extract all FRED series IDs and titles for gold driver audit."""
import json
import re

def main():
    with open('src/scripts/FRED/all_series_merged.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    series_data = data.get('series', {})
    series_by_id = {}
    
    if isinstance(series_data, dict):
        for sid, item in series_data.items():
            if isinstance(item, dict):
                series_by_id[sid] = {
                    'id': sid,
                    'title': item.get('title', ''),
                    'units': item.get('units', ''),
                }
    elif isinstance(series_data, list):
        for item in series_data:
            sid = item.get('id') if isinstance(item, dict) else None
            if sid:
                series_by_id[sid] = {
                    'id': sid,
                    'title': item.get('title', ''),
                    'units': item.get('units', ''),
                }
    
    ids = list(series_by_id.keys())
    
    # Search for gold-relevant series
    gold_keywords = {
        'Real Interest Rates / 10Y': ['DGS10', 'DGS2', 'GS10', 'T10YIE', 'T5YIE', 'DFII10', 'TIPS', 'real yield'],
        'Monetary Policy': ['FEDFUNDS', 'DFEDTAR', 'EFFR', 'FED', 'balance sheet', 'WALCL', 'WLCFLPCL'],
        'US Dollar': ['DXY', 'DTWEX', 'TWEX', 'trade.weighted', 'trade weighted', 'DEX'],
        'Inflation': ['CPIAUCSL', 'CPILFESL', 'CUSR0000SA0', 'PCEPI', 'PCE', 'CPI', 'inflation'],
        'GDP': ['GDP', 'GDPC1', 'A191RL1', 'real gdp'],
        'Employment': ['PAYEMS', 'UNRATE', 'ICSA', 'CE16OV', 'nonfarm', 'payroll', 'unemployment'],
        'VIX': ['VIX', 'VIXCLS'],
        'S&P 500': ['SP500', 'SPX', '^GSPC'],
        'Gold': ['GOLD', 'GOLDPM', ' gold ', 'gold price', 'LBMA', 'XAU'],
        'ETF': ['GLD', 'IAU', 'ETF', 'gold holding'],
        'Central Bank Reserves': ['gold reserve', 'central bank gold', 'official gold'],
        'Mining': ['gold product', 'mining', 'gold product'],
        'Economic Policy Uncertainty': ['EPU', 'policy uncertainty', 'EPU'],
    }
    
    found = {}
    for kid, kws in gold_keywords.items():
        found[kid] = []
    
    for sid, info in series_by_id.items():
        title_lower = (info.get('title') or '').lower()
        units_lower = (info.get('units') or '').lower()
        combined = f"{sid} {title_lower} {units_lower}"
        
        for kid, kws in gold_keywords.items():
            for kw in kws:
                if kw.lower() in sid or kw.lower() in combined:
                    found[kid].append({'id': sid, 'title': info.get('title', '')[:80]})
                    break
    
    # Output all IDs for manual mapping
    with open('src/scripts/FRED/audit_output.txt', 'w', encoding='utf-8') as out:
        out.write(f"Total series: {len(ids)}\n\n")
        out.write("=== Gold-relevant matches ===\n")
        for kid, matches in found.items():
            out.write(f"\n{kid}:\n")
            for m in matches[:15]:
                out.write(f"  {m['id']}: {m['title']}\n")
        
        out.write("\n\n=== All series IDs (for grep) ===\n")
        out.write(" ".join(sorted(ids)))
    
    print(f"Total series: {len(ids)}")
    for kid, matches in found.items():
        print(f"{kid}: {len(matches)} matches")
