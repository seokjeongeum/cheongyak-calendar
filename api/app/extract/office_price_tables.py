"""Read a printed office price table by its stock counts and checked sums."""
from __future__ import annotations

import re


def office_price_tables(pages, *, make):
    stock = []
    for page in pages:
        compact = re.sub(r'\s+', '', page['text'])
        if not all(label in compact for label in ('공급호실', '전용면적', '계약면적')):
            continue
        for match in re.finditer(r'(?<![\w.])(\d+[A-Z])\s+(\d+)\s+(\d+\.\d+)\s+(\d+\.\d+)\s+(\d+\.\d+)', page['text']):
            # Printed exclusive + common area must reconcile to their subtotal.
            exclusive, common, subtotal = map(float, match.groups()[2:])
            if abs(exclusive + common - subtotal) > .00011:
                return [], []
            stock.append({'unit_type': match[1], 'count': int(match[2]), 'exclusive_area_sqm': exclusive,
                          'page': page['page'], 'quote': match[0]})
    if not stock or len({row['unit_type'] for row in stock}) != len(stock) or any(row['count'] < 1 for row in stock):
        return [], []
    declared = sum(row['count'] for row in stock)
    rows = []
    header_page = None
    money = r'([\d,]{7,})'
    for page in pages:
        compact = re.sub(r'\s+', '', page['text'])
        if not all(label in compact for label in ('공급금액', '대지비', '건물비', '부가세', '계약금', '잔금')):
            continue
        # Exact semantic columns, currency unit and every row's independent
        # total gates prevent an installment/deposit from becoming sale price.
        if not re.search(r'단위[^\]]{0,20}원', compact) or not re.search(r'대지비건물비부가세계', compact):
            continue
        header_page = page['page']
        pattern = r'(\d+)\s+(\d{3,5})\s+' + r'\s+'.join([money] * 6)
        for match in re.finditer(pattern, page['text']):
            values = [int(value.replace(',', '')) for value in match.groups()[2:]]
            land, building, vat, total, first, rest = values
            if land + building + vat != total or first + rest != total:
                return [], []
            rows.append({'total': total, 'page': page['page'], 'quote': match[0]})
    if len(rows) != declared or header_page is None:
        return [], []
    prices = []
    offset = 0
    for unit in stock:
        group = rows[offset:offset + unit['count']]
        offset += unit['count']
        maximum = max(group, key=lambda row: row['total'])
        evidence = make('office_price_table', quote=maximum['quote'], page=maximum['page'])
        prices.append({'unit_type': unit['unit_type'], 'area_sqm': unit['exclusive_area_sqm'], 'amount_krw': maximum['total'],
                       'price_kind': 'sale_max', 'monthly_krw': None, 'basis_label': '타입별 최고 공급금액 · 부가세 포함',
                       **{key: evidence[key] for key in ('verification', 'source', 'document_hash', 'evidence_url', 'evidence_text', 'evidence_page')}})
    # Original order is validated using the printed unit markers. A document
    # with ambiguous sorting/repeated headings is left for review.
    table_text = '\n'.join(page['text'] for page in pages if page['page'] == header_page)
    markers = [m[0] for m in re.finditer(r'(?<![\w.])\d+[A-Z](?![\w.])', table_text)]
    ordered_markers = list(dict.fromkeys(markers))
    if ordered_markers != [unit['unit_type'] for unit in stock]:
        return [], []
    areas = make('unit_exclusive_areas', effect='metadata', units=[{'unit_type': u['unit_type'], 'exclusive_area_sqm': u['exclusive_area_sqm']} for u in stock],
                 page=stock[0]['page'], quote=' / '.join(u['quote'] for u in stock))
    fees = []
    for page in pages:
        match = re.search(r'모든\s*타입\s*공통\s*([\d,]+)원', page['text'])
        if match and '청약신청금' in re.sub(r'\s+', '', page['text']):
            fees.append(make('supply_financial_terms', effect='metadata', units=[{'unit_type': u['unit_type'], 'application_fee_krw': int(match[1].replace(',', ''))} for u in stock],
                             quote=match[0], page=page['page']))
    return prices, [areas, *fees]
