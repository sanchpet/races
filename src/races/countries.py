"""Resolve the many ways sources spell a country into ISO 3166-1 alpha-2."""

from __future__ import annotations

from functools import cache

import pycountry

# Names pycountry does not resolve on its own (it knows "Türkiye", "Viet Nam", ...).
NAME_OVERRIDES = {
    "chinese taipei": "TW",
    "taiwan": "TW",
    "turkey": "TR",
    "russia": "RU",
    "south korea": "KR",
    "korea": "KR",
    "north korea": "KP",
    "vietnam": "VN",
    "iran": "IR",
    "syria": "SY",
    "laos": "LA",
    "moldova": "MD",
    "bolivia": "BO",
    "venezuela": "VE",
    "tanzania": "TZ",
    "palestine": "PS",
    "kosovo": "XK",
    "czech republic": "CZ",
    "macau": "MO",
    "hong kong": "HK",
    "england": "GB",
    "scotland": "GB",
    "wales": "GB",
    "northern ireland": "GB",
    "uk": "GB",
    "usa": "US",
    "uae": "AE",
    "reunion": "RE",
    "la reunion": "RE",
    "cape verde": "CV",
    "ivory coast": "CI",
    "swaziland": "SZ",
    "macedonia": "MK",
    "sakartvelo": "GE",
}

# IOC codes that are not also the country's ISO alpha-3 code. Some collide with a
# different ISO country (IOC BRN is Bahrain, ISO BRN is Brunei), so this table wins.
IOC_OVERRIDES = {
    "ALG": "DZ",
    "ANG": "AO",
    "ANT": "AG",
    "ARU": "AW",
    "ASA": "AS",
    "BAH": "BS",
    "BAN": "BD",
    "BAR": "BB",
    "BER": "BM",
    "BHU": "BT",
    "BIZ": "BZ",
    "BOT": "BW",
    "BRN": "BH",
    "BRU": "BN",
    "BUL": "BG",
    "BUR": "BF",
    "CAM": "KH",
    "CAY": "KY",
    "CGO": "CG",
    "CHA": "TD",
    "CHI": "CL",
    "CRC": "CR",
    "CRO": "HR",
    "DEN": "DK",
    "ESA": "SV",
    "FIJ": "FJ",
    "GAM": "GM",
    "GBS": "GW",
    "GER": "DE",
    "GRE": "GR",
    "GRN": "GD",
    "GUA": "GT",
    "GUI": "GN",
    "HAI": "HT",
    "HON": "HN",
    "INA": "ID",
    "IRI": "IR",
    "ISV": "VI",
    "IVB": "VG",
    "KOS": "XK",
    "KSA": "SA",
    "KUW": "KW",
    "LAT": "LV",
    "LBA": "LY",
    "LES": "LS",
    "LCA": "LC",
    "MAD": "MG",
    "MAS": "MY",
    "MAW": "MW",
    "MGL": "MN",
    "MON": "MC",
    "MRI": "MU",
    "MTN": "MR",
    "MYA": "MM",
    "NCA": "NI",
    "NED": "NL",
    "NEP": "NP",
    "NGR": "NG",
    "NIG": "NE",
    "OMA": "OM",
    "PAR": "PY",
    "PHI": "PH",
    "POR": "PT",
    "PUR": "PR",
    "RSA": "ZA",
    "SAM": "WS",
    "SEY": "SC",
    "SKN": "KN",
    "SLE": "SL",
    "SLO": "SI",
    "SOL": "SB",
    "SRI": "LK",
    "SUD": "SD",
    "SUI": "CH",
    "TAN": "TZ",
    "TGA": "TO",
    "TOG": "TG",
    "TPE": "TW",
    "TRI": "TT",
    "UAE": "AE",
    "URU": "UY",
    "VAN": "VU",
    "VIE": "VN",
    "VIN": "VC",
    "ZAM": "ZM",
    "ZIM": "ZW",
    "ENG": "GB",
    "SCO": "GB",
    "WAL": "GB",
}


@cache
def from_name(name: str | None) -> str | None:
    if not name:
        return None
    key = name.strip().lower()
    if key in NAME_OVERRIDES:
        return NAME_OVERRIDES[key]
    try:
        return pycountry.countries.lookup(name.strip()).alpha_2
    except LookupError:
        return None


@cache
def from_ioc(code: str | None) -> str | None:
    if not code:
        return None
    code = code.strip().upper()
    if code in IOC_OVERRIDES:
        return IOC_OVERRIDES[code]
    country = pycountry.countries.get(alpha_3=code)
    return country.alpha_2 if country else None


def name_of(alpha_2: str) -> str:
    if alpha_2 == "XK":
        return "Kosovo"
    country = pycountry.countries.get(alpha_2=alpha_2)
    if country is None:
        return alpha_2
    return getattr(country, "common_name", None) or country.name
