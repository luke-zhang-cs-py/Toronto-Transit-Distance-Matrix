"""
Everything outside downtown Toronto: York Region Transit / Viva
(Vaughan, Richmond Hill, Markham, Newmarket), MiWay (Mississauga), and
the highway-corridor hubs (Hwy 400/401/403/404/407/QEW) that tie the
three regions to each other and to the TTC network. Rougher than the
downtown model on purpose — a handful of representative corridors per
agency, not a full route-by-route rebuild.

Must run after network.subway.build() — several edges here connect to
subway stations (union, kipling, finch, vaughanmc) that need to exist
first.
"""

from .graph import chain, add_node, add_edge

YRT_HOP = 8     # typical minutes between Viva rapid-bus stops
GO_HOP = 24     # Union <-> Mississauga City Centre, rail + connecting bus
MIWAY_HOP = 18  # Kipling <-> Mississauga City Centre express bus

# ---- YRT / Viva: Vaughan, Richmond Hill, Markham ----
YRT_PURPLE = [
    {'id': 'vaughanmills', 'name': 'Vaughan Mills', 'lat': 43.8005, 'lon': -79.5372},
    {'id': 'vaughanmc', 'name': 'Vaughan Metropolitan Centre', 'lat': 43.7955, 'lon': -79.5265},
    {'id': 'richmondhillcentre', 'name': 'Richmond Hill Centre', 'lat': 43.8517, 'lon': -79.4265},
    {'id': 'markhamcentre', 'name': 'Markham Centre', 'lat': 43.8564, 'lon': -79.3370},
    {'id': 'unionville', 'name': 'Unionville', 'lat': 43.8686, 'lon': -79.3096},
]

YRT_ORANGE = [
    {'id': 'newmarket', 'name': 'Newmarket (Davis Dr)', 'lat': 43.9436, 'lon': -79.4744},
    {'id': 'richmondhillyonge', 'name': 'Richmond Hill (Yonge & 16th)', 'lat': 43.8828, 'lon': -79.4403},
    {'id': 'steelesyonge', 'name': 'Steeles & Yonge', 'lat': 43.7947, 'lon': -79.4103},
    {'id': 'finch', 'name': 'Finch', 'lat': 43.7807, 'lon': -79.4147},
]

MIWAY_HUBS = [
    ('cooksvillego', 'Cooksville GO', 43.5836, -79.6122),
    ('dixieoutletmall', 'Dixie & Dundas', 43.6188, -79.5820),
    ('portcreditgo', 'Port Credit GO', 43.5583, -79.5943),
    ('clarksongo', 'Clarkson GO', 43.5199, -79.6392),
    ('erinmillstc', 'Erin Mills Town Centre', 43.5698, -79.6928),
    ('streetsvillego', 'Streetsville GO', 43.5847, -79.7188),
    ('meadowvaletc', 'Meadowvale Town Centre', 43.5924, -79.7477),
    ('malton', 'Malton', 43.7128, -79.6300),
    ('airportcorporate', 'Airport Corporate Centre', 43.6815, -79.6300),
]

# Major highway-adjacent interchanges — added so the reach map has more
# than one or two spokes per outer city.
HIGHWAY_NODES = [
    # Mississauga: Hwy 401 / 403 / QEW
    ('renforth', 'Renforth Gateway (Hwy 401)', 43.6802, -79.5875),
    ('hwy403', 'Hwy 403 & Eglinton', 43.5658, -79.6890),
    ('qewcawthra', 'QEW & Cawthra', 43.5751, -79.6039),
    # Vaughan: Hwy 400
    ('concordgo', 'Concord GO (Hwy 7/400)', 43.8106, -79.4963),
    ('hwy400rutherford', 'Hwy 400 & Rutherford', 43.8225, -79.5280),
    # Markham: Hwy 404 / 407
    ('hwy404_16th', 'Hwy 404 & 16th Ave', 43.8562, -79.3608),
    ('centennialgo', 'Centennial GO (Hwy 7/Kennedy)', 43.8412, -79.2938),
    ('hwy407kennedy', 'Hwy 407 & Kennedy', 43.8390, -79.3287),
]


def _build_yrt():
    chain(YRT_PURPLE, YRT_HOP, 'yrt', 'YRT Viva Purple (Hwy 7)')
    chain(YRT_ORANGE, 14, 'yrt', 'YRT Viva Orange (Yonge St)')

    add_node('thornhill', 'Thornhill (Yonge & Centre)', 43.8156, -79.4256, 'yrt')
    add_edge('steelesyonge', 'thornhill', 6, 'YRT local')
    add_edge('thornhill', 'richmondhillcentre', 10, 'YRT local')
    add_edge('richmondhillyonge', 'richmondhillcentre', 9, 'YRT local')

    add_node('cornell', 'Cornell (Markham east)', 43.8752, -79.2519, 'yrt')
    add_edge('markhamcentre', 'cornell', 14, 'YRT Viva Blue (Hwy 7 east)')


def _build_miway():
    add_node('mississaugacc', 'Mississauga City Centre (Square One)', 43.5932, -79.6416, 'go')
    add_edge('union', 'mississaugacc', GO_HOP, 'GO Transit (Milton/Lakeshore W + bus)')
    add_edge('kipling', 'mississaugacc', MIWAY_HOP, 'MiWay Express')

    for nid, name, lat, lon in MIWAY_HUBS:
        add_node(nid, name, lat, lon, 'miway')

    add_edge('meadowvaletc', 'mississaugacc', 14, 'MiWay Hurontario corridor')
    add_edge('mississaugacc', 'cooksvillego', 8, 'MiWay Hurontario corridor')
    add_edge('cooksvillego', 'dixieoutletmall', 10, 'MiWay Hurontario corridor')
    add_edge('dixieoutletmall', 'portcreditgo', 12, 'MiWay Hurontario corridor')
    add_edge('erinmillstc', 'mississaugacc', 12, 'MiWay Dundas corridor')
    add_edge('streetsvillego', 'erinmillstc', 10, 'MiWay west end')
    add_edge('streetsvillego', 'meadowvaletc', 9, 'MiWay west end')
    add_edge('clarksongo', 'portcreditgo', 8, 'MiWay Lakeshore corridor')
    add_edge('malton', 'airportcorporate', 10, 'MiWay Airport corridor')
    add_edge('airportcorporate', 'mississaugacc', 14, 'MiWay Airport corridor')


def _build_highways():
    for nid, name, lat, lon in HIGHWAY_NODES:
        mode = 'yrt' if nid.startswith(('concord', 'hwy400', 'hwy404', 'centennial', 'hwy407')) else 'miway'
        add_node(nid, name, lat, lon, mode)

    add_edge('renforth', 'airportcorporate', 8, 'MiWay Hwy 401 corridor')
    add_edge('renforth', 'kipling', 12, 'MiWay Hwy 401 corridor')
    add_edge('hwy403', 'erinmillstc', 7, 'MiWay Hwy 403 corridor')
    add_edge('hwy403', 'mississaugacc', 10, 'MiWay Hwy 403 corridor')
    add_edge('qewcawthra', 'portcreditgo', 6, 'MiWay QEW corridor')
    add_edge('qewcawthra', 'clarksongo', 7, 'MiWay QEW corridor')
    add_edge('qewcawthra', 'dixieoutletmall', 8, 'MiWay QEW corridor')

    add_edge('concordgo', 'vaughanmc', 9, 'YRT Hwy 400 corridor')
    add_edge('concordgo', 'vaughanmills', 6, 'YRT Hwy 400 corridor')
    add_edge('hwy400rutherford', 'vaughanmills', 5, 'YRT Hwy 400 corridor')
    add_edge('hwy400rutherford', 'concordgo', 7, 'YRT Hwy 400 corridor')

    add_edge('hwy404_16th', 'markhamcentre', 6, 'YRT Hwy 404 corridor')
    add_edge('hwy404_16th', 'unionville', 8, 'YRT Hwy 404 corridor')
    add_edge('centennialgo', 'cornell', 7, 'YRT Hwy 7 east corridor')
    add_edge('centennialgo', 'unionville', 9, 'YRT Hwy 7 east corridor')
    add_edge('hwy407kennedy', 'centennialgo', 5, 'YRT Hwy 407 corridor')
    add_edge('hwy407kennedy', 'markhamcentre', 7, 'YRT Hwy 407 corridor')


def build():
    _build_yrt()
    _build_miway()
    _build_highways()
