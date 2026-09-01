"""
Downtown streetcar grid: the Spadina/Bathurst vertical corridors, the
King/Queen/Dundas/College horizontal rows, the Harbourfront connector,
and the manual transfer links that tie the streetcar grid back into the
subway (Line 1 / Line 2) at real interchange points.
"""

from .graph import chain, add_edge, TRANSFER

TRAM_HOP = 2.3  # minutes between adjacent streetcar stops

# ---- streetcar grid coordinates ----
street_x = {'dufferin': -79.4353, 'ossington': -79.4218, 'bathurst': -79.4113,
            'spadina': -79.4038, 'university': -79.3900, 'yonge': -79.3832,
            'church': -79.3776, 'parliament': -79.3696, 'broadview': -79.3583,
            'coxwell': -79.3277}
row_y = {'queensquay': 43.6386, 'king': 43.6489, 'queen': 43.6529,
         'dundas': 43.6564, 'college': 43.6610}

# ---- vertical corridors: 510 Spadina / 511 Bathurst ----
SPADINA_TRAM = [
    {'id': 'spadina_qq', 'name': 'Spadina & Queens Quay', 'lat': row_y['queensquay'], 'lon': street_x['spadina']},
    {'id': 'spadina_king', 'name': 'Spadina & King', 'lat': row_y['king'], 'lon': street_x['spadina']},
    {'id': 'spadina_queen', 'name': 'Spadina & Queen', 'lat': row_y['queen'], 'lon': street_x['spadina']},
    {'id': 'spadina_dundas', 'name': 'Spadina & Dundas', 'lat': row_y['dundas'], 'lon': street_x['spadina']},
    {'id': 'spadina_college', 'name': 'Spadina & College', 'lat': row_y['college'], 'lon': street_x['spadina']},
    {'id': 'spadina', 'name': 'Spadina', 'lat': 43.6674, 'lon': -79.4038},
]

BATHURST_TRAM = [
    {'id': 'bathurst_qq', 'name': 'Bathurst & Fleet', 'lat': 43.6375, 'lon': street_x['bathurst']},
    {'id': 'bathurst_king', 'name': 'Bathurst & King', 'lat': row_y['king'], 'lon': street_x['bathurst']},
    {'id': 'bathurst_queen', 'name': 'Bathurst & Queen', 'lat': row_y['queen'], 'lon': street_x['bathurst']},
    {'id': 'bathurst_dundas', 'name': 'Bathurst & Dundas', 'lat': row_y['dundas'], 'lon': street_x['bathurst']},
    {'id': 'bathurst_college', 'name': 'Bathurst & College', 'lat': row_y['college'], 'lon': street_x['bathurst']},
    {'id': 'bathurst', 'name': 'Bathurst', 'lat': 43.6664, 'lon': -79.4113},
]

# ---- horizontal rows: 504 King / 501 Queen / 505 Dundas / 506 Carlton-College ----
ROW_LINE_NAMES = {'king': '504 King', 'queen': '501 Queen', 'dundas': '505 Dundas',
                   'college': '506 Carlton/College'}


def _build_row(row_name):
    cols = list(street_x.keys())
    seq = []
    for c in cols:
        if c == 'spadina':
            nid = f'spadina_{row_name}'
        elif c == 'bathurst':
            nid = f'bathurst_{row_name}'
        else:
            nid = f'{row_name}row_{c}'
        seq.append({'id': nid, 'name': f"{c.capitalize()} & {row_name.capitalize()}",
                    'lat': row_y[row_name], 'lon': street_x[c]})
    return seq


HROWS = {row_name: _build_row(row_name) for row_name in ['king', 'queen', 'dundas', 'college']}

# ---- Harbourfront connector ----
HARBOUR = [
    {'id': 'spadina_qq', 'name': 'Spadina & Queens Quay', 'lat': row_y['queensquay'], 'lon': street_x['spadina']},
    {'id': 'union_qq', 'name': 'Union & Queens Quay', 'lat': row_y['queensquay'], 'lon': -79.3800},
    {'id': 'yonge_qq', 'name': 'Yonge & Queens Quay', 'lat': row_y['queensquay'], 'lon': street_x['yonge']},
]

# ---- manual subway <-> streetcar transfer links ----
TRANSFERS = [
    ('king', 'kingrow_yonge', TRANSFER),
    ('queen', 'queenrow_yonge', TRANSFER),
    ('dundas', 'dundasrow_yonge', TRANSFER),
    ('college', 'collegerow_yonge', TRANSFER),
    ('standrew', 'kingrow_university', TRANSFER),
    ('osgoode', 'queenrow_university', TRANSFER),
    ('stpatrick', 'dundasrow_university', TRANSFER),
    ('queenspark', 'collegerow_university', TRANSFER),
    ('union', 'union_qq', TRANSFER + 1),
    ('union', 'spadina_king', TRANSFER + 2),
    ('broadview', 'kingrow_broadview', TRANSFER + 2),
    ('christie', 'collegerow_ossington', TRANSFER + 3),
]


def build():
    """Add every streetcar station/edge, then the subway transfer links.
    Must run after network.subway.build() — the transfer links and the
    Union/Spadina/Bathurst/Christie/Broadview shared nodes assume the
    subway stations already exist."""
    chain(SPADINA_TRAM, TRAM_HOP, 'tram', '510 Spadina')
    chain(BATHURST_TRAM, TRAM_HOP, 'tram', '511 Bathurst')
    for row_name, seq in HROWS.items():
        chain(seq, TRAM_HOP, 'tram', ROW_LINE_NAMES[row_name])
    chain(HARBOUR, TRAM_HOP, 'tram', '509/510 Harbourfront')
    for a, b, t in TRANSFERS:
        add_edge(a, b, t, 'Transfer')
