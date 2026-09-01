"""
TTC subway: Line 1 (Yonge-University) and Line 2 (Bloor-Danforth),
including their real outer extensions — Line 1 north to Finch and to
Vaughan Metropolitan Centre, Line 2 west to Kipling — since those are
the actual gateways the regional networks connect into.
"""

from .graph import chain

SUBWAY_HOP = 2.2  # minutes between adjacent downtown stops

# ---- Subway Line 1 (Yonge-University) ----
LINE1 = [
    {'id': 'spadina', 'name': 'Spadina', 'lat': 43.6674, 'lon': -79.4038},
    {'id': 'stgeorge', 'name': 'St George', 'lat': 43.6683, 'lon': -79.3999},
    {'id': 'museum', 'name': 'Museum', 'lat': 43.6677, 'lon': -79.3948},
    {'id': 'queenspark', 'name': "Queen's Park", 'lat': 43.6640, 'lon': -79.3919},
    {'id': 'stpatrick', 'name': 'St Patrick', 'lat': 43.6549, 'lon': -79.3877},
    {'id': 'osgoode', 'name': 'Osgoode', 'lat': 43.6505, 'lon': -79.3866},
    {'id': 'standrew', 'name': 'St Andrew', 'lat': 43.6474, 'lon': -79.3832},
    {'id': 'union', 'name': 'Union', 'lat': 43.6453, 'lon': -79.3806},
    {'id': 'king', 'name': 'King', 'lat': 43.6489, 'lon': -79.3781},
    {'id': 'queen', 'name': 'Queen', 'lat': 43.6529, 'lon': -79.3795},
    {'id': 'dundas', 'name': 'Dundas (TMU)', 'lat': 43.6564, 'lon': -79.3805},
    {'id': 'college', 'name': 'College', 'lat': 43.6610, 'lon': -79.3835},
    {'id': 'wellesley', 'name': 'Wellesley', 'lat': 43.6654, 'lon': -79.3839},
    {'id': 'blooryonge', 'name': 'Bloor-Yonge', 'lat': 43.6708, 'lon': -79.3860},
]

# ---- Subway Line 2 (Bloor-Danforth) ----
LINE2 = [
    {'id': 'christie', 'name': 'Christie', 'lat': 43.6642, 'lon': -79.4198},
    {'id': 'bathurst', 'name': 'Bathurst', 'lat': 43.6664, 'lon': -79.4113},
    {'id': 'spadina', 'name': 'Spadina', 'lat': 43.6674, 'lon': -79.4038},
    {'id': 'stgeorge', 'name': 'St George', 'lat': 43.6683, 'lon': -79.3999},
    {'id': 'bay', 'name': 'Bay', 'lat': 43.6699, 'lon': -79.3906},
    {'id': 'blooryonge', 'name': 'Bloor-Yonge', 'lat': 43.6708, 'lon': -79.3860},
    {'id': 'sherbourne', 'name': 'Sherbourne', 'lat': 43.6721, 'lon': -79.3757},
    {'id': 'castlefrank', 'name': 'Castle Frank', 'lat': 43.6737, 'lon': -79.3691},
    {'id': 'broadview', 'name': 'Broadview', 'lat': 43.6767, 'lon': -79.3583},
    {'id': 'chester', 'name': 'Chester', 'lat': 43.6784, 'lon': -79.3527},
]

# ---- Line 1 north extension: Yonge side up to Finch ----
LINE1_NORTH_YONGE = [
    {'id': 'blooryonge', 'name': 'Bloor-Yonge', 'lat': 43.6708, 'lon': -79.3860},
    {'id': 'rosedale', 'name': 'Rosedale', 'lat': 43.6766, 'lon': -79.3893},
    {'id': 'summerhill', 'name': 'Summerhill', 'lat': 43.6822, 'lon': -79.3906},
    {'id': 'stclair', 'name': 'St Clair', 'lat': 43.6879, 'lon': -79.3931},
    {'id': 'davisville', 'name': 'Davisville', 'lat': 43.6979, 'lon': -79.3966},
    {'id': 'eglinton', 'name': 'Eglinton', 'lat': 43.7063, 'lon': -79.3986},
    {'id': 'lawrence', 'name': 'Lawrence', 'lat': 43.7250, 'lon': -79.4023},
    {'id': 'yorkmills', 'name': 'York Mills', 'lat': 43.7423, 'lon': -79.4053},
    {'id': 'sheppardyonge', 'name': 'Sheppard-Yonge', 'lat': 43.7614, 'lon': -79.4108},
    {'id': 'northyorkcentre', 'name': 'North York Centre', 'lat': 43.7686, 'lon': -79.4132},
    {'id': 'finch', 'name': 'Finch', 'lat': 43.7807, 'lon': -79.4147},
]

# ---- Line 1 north extension: University side up to Vaughan Metropolitan Centre ----
LINE1_NORTHWEST = [
    {'id': 'spadina', 'name': 'Spadina', 'lat': 43.6674, 'lon': -79.4038},
    {'id': 'dupont', 'name': 'Dupont', 'lat': 43.6748, 'lon': -79.4066},
    {'id': 'stclairwest', 'name': 'St Clair West', 'lat': 43.6839, 'lon': -79.4149},
    {'id': 'eglintonwest', 'name': 'Eglinton West (Cedarvale)', 'lat': 43.6996, 'lon': -79.4390},
    {'id': 'glencairn', 'name': 'Glencairn', 'lat': 43.7085, 'lon': -79.4416},
    {'id': 'lawrencewest', 'name': 'Lawrence West', 'lat': 43.7159, 'lon': -79.4457},
    {'id': 'yorkdale', 'name': 'Yorkdale', 'lat': 43.7223, 'lon': -79.4526},
    {'id': 'wilson', 'name': 'Wilson', 'lat': 43.7347, 'lon': -79.4491},
    {'id': 'sheppardwest', 'name': 'Sheppard West', 'lat': 43.7486, 'lon': -79.4633},
    {'id': 'downsviewpark', 'name': 'Downsview Park', 'lat': 43.7501, 'lon': -79.4788},
    {'id': 'finchwest', 'name': 'Finch West', 'lat': 43.7654, 'lon': -79.4904},
    {'id': 'yorkuniversity', 'name': 'York University', 'lat': 43.7735, 'lon': -79.5038},
    {'id': 'pioneervillage', 'name': 'Pioneer Village', 'lat': 43.7791, 'lon': -79.5153},
    {'id': 'hwy407', 'name': 'Highway 407', 'lat': 43.7834, 'lon': -79.5195},
    {'id': 'vaughanmc', 'name': 'Vaughan Metropolitan Centre', 'lat': 43.7955, 'lon': -79.5265},
]

# ---- Line 2 west extension to Kipling (gateway toward Mississauga) ----
LINE2_WEST = [
    {'id': 'christie', 'name': 'Christie', 'lat': 43.6642, 'lon': -79.4198},
    {'id': 'ossington', 'name': 'Ossington', 'lat': 43.6636, 'lon': -79.4265},
    {'id': 'dufferin', 'name': 'Dufferin', 'lat': 43.6602, 'lon': -79.4356},
    {'id': 'lansdowne', 'name': 'Lansdowne', 'lat': 43.6566, 'lon': -79.4372},
    {'id': 'dundaswest', 'name': 'Dundas West', 'lat': 43.6564, 'lon': -79.4527},
    {'id': 'keele', 'name': 'Keele', 'lat': 43.6559, 'lon': -79.4650},
    {'id': 'highpark', 'name': 'High Park', 'lat': 43.6542, 'lon': -79.4664},
    {'id': 'runnymede', 'name': 'Runnymede', 'lat': 43.6511, 'lon': -79.4759},
    {'id': 'oldmill', 'name': 'Old Mill', 'lat': 43.6493, 'lon': -79.4830},
    {'id': 'jane', 'name': 'Jane', 'lat': 43.6497, 'lon': -79.4900},
    {'id': 'royalyork', 'name': 'Royal York', 'lat': 43.6461, 'lon': -79.5228},
    {'id': 'islington', 'name': 'Islington', 'lat': 43.6461, 'lon': -79.5288},
    {'id': 'kipling', 'name': 'Kipling', 'lat': 43.6367, 'lon': -79.5352},
]


def build():
    """Add every subway station and edge into the shared graph."""
    chain(LINE1, SUBWAY_HOP, 'subway', 'Line 1 (Yonge-University)')
    chain(LINE2, SUBWAY_HOP, 'subway', 'Line 2 (Bloor-Danforth)')
    chain(LINE1_NORTH_YONGE, SUBWAY_HOP + 0.3, 'subway', 'Line 1 (Yonge-University)')
    chain(LINE1_NORTHWEST, SUBWAY_HOP + 0.3, 'subway', 'Line 1 (Yonge-University)')
    chain(LINE2_WEST, SUBWAY_HOP, 'subway', 'Line 2 (Bloor-Danforth)')
