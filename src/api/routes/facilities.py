"""Facilities API routes."""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/facilities", tags=["facilities"])


class Facility(BaseModel):
    """Tennis facility."""

    code: str
    name: str
    address: str
    latitude: float
    longitude: float


# All 44 Paris Tennis facilities from official spreadsheet
FACILITIES = [
    Facility(
        code="2",
        name="Amandiers",
        address="8 rue Louis Delgrès, 75020 Paris",
        latitude=48.83805,
        longitude=2.41041,
    ),
    Facility(
        code="12",
        name="Atlantique",
        address="25 allée du Capitaine Dronne, 75015 Paris",
        latitude=48.8656,
        longitude=2.38669,
    ),
    Facility(
        code="15",
        name="Philippe Auguste",
        address="108 avenue Philippe Auguste, 75011 Paris",
        latitude=48.83957,
        longitude=2.3174,
    ),
    Facility(
        code="23",
        name="Porte de Bagnolet",
        address="72 rue Louis Lumière, 75020 Paris",
        latitude=48.88309,
        longitude=2.28208,
    ),
    Facility(
        code="53",
        name="Candie",
        address="11 rue Candie, 75011 Paris",
        latitude=48.89949,
        longitude=2.34235,
    ),
    Facility(
        code="58",
        name="Carnot",
        address="26 boulevard Carnot, 75012 Paris",
        latitude=48.90956,
        longitude=2.4202,
    ),
    Facility(
        code="60",
        name="Georges Carpentier",
        address="5 Place de Port au Prince, 75013 Paris",
        latitude=48.85138,
        longitude=2.38002,
    ),
    Facility(
        code="67",
        name="Jesse Owens",
        address="172 rue Championnet, 75018 Paris",
        latitude=48.84297,
        longitude=2.4128,
    ),
    Facility(
        code="79",
        name="Reims - Asnières",
        address="34 boulevard de Reims, 75017 Paris",
        latitude=48.83049,
        longitude=2.36207,
    ),
    Facility(
        code="81",
        name="Courcelles",
        address="211 rue de Courcelles, 75017 Paris",
        latitude=48.83336,
        longitude=2.3486,
    ),
    Facility(
        code="85",
        name="Aurelle de Paladines",
        address="10 rue Parmentier, 92200 Neuilly sur Seine",
        latitude=48.88919,
        longitude=2.29245,
    ),
    Facility(
        code="92",
        name="Bertrand Dauvin",
        address="12 rue René Binet, 75018 Paris",
        latitude=48.84245,
        longitude=2.29457,
    ),
    Facility(
        code="98",
        name="Docteurs Déjerine",
        address="32-36 rue des Docteurs Déjerine, 75020 Paris",
        latitude=48.85601,
        longitude=2.41219,
    ),
    Facility(
        code="109",
        name="Dunois",
        address="70 rue Dunois, 75013 Paris",
        latitude=48.83308,
        longitude=2.36637,
    ),
    Facility(
        code="120",
        name="Elisabeth",
        address="7 avenue Paul Appell, 75014 Paris",
        latitude=48.88059,
        longitude=2.37701,
    ),
    Facility(
        code="126",
        name="La Faluère",
        address="route de la Pyramide, 75012 Paris",
        latitude=48.82126,
        longitude=2.32885,
    ),
    Facility(
        code="155",
        name="Jandelle",
        address="15-17 cité Jandelle, 75019 Paris",
        latitude=48.82059,
        longitude=2.36744,
    ),
    Facility(
        code="174",
        name="Léo Lagrange",
        address="68 boulevard Poniatowski, 75012 Paris",
        latitude=48.89688,
        longitude=2.35642,
    ),
    Facility(
        code="188",
        name="Suzanne Lenglen",
        address="2 rue Louis Armand, 75015 Paris",
        latitude=48.86736,
        longitude=2.27145,
    ),
    Facility(
        code="198",
        name="Louis Lumière",
        address="30 rue Louis Lumière, 75020 Paris",
        latitude=48.8753,
        longitude=2.3798,
    ),
    Facility(
        code="218",
        name="Moureu - Baudricourt",
        address="17 avenue Edison, 75013 Paris",
        latitude=48.89493,
        longitude=2.33551,
    ),
    Facility(
        code="220",
        name="René et André Mourlon",
        address="19 rue Gaston de Caillavet, 75015 Paris",
        latitude=48.89271,
        longitude=2.39696,
    ),
    Facility(
        code="233",
        name="Croix Nivert",
        address="107 rue de la Croix Nivert, 75015 Paris",
        latitude=48.8303,
        longitude=2.45013,
    ),
    Facility(
        code="240",
        name="Edouard Pailleron",
        address="24 rue Edouard Pailleron, 75019 Paris",
        latitude=48.85887,
        longitude=2.41172,
    ),
    Facility(
        code="258",
        name="Rigoulot - La Plaine",
        address="18 avenue de la Porte de Brancion, 75015 Paris",
        latitude=48.83208,
        longitude=2.39914,
    ),
    Facility(
        code="264",
        name="Poissonniers",
        address="2 rue Jean Cocteau, 75018 Paris",
        latitude=48.89891,
        longitude=2.32533,
    ),
    Facility(
        code="267",
        name="Poliveau",
        address="39bis rue de Poliveau, 75005 Paris",
        latitude=48.82766,
        longitude=2.36411,
    ),
    Facility(
        code="272",
        name="Poterne des Peupliers",
        address="17 rue Max Jacob, 75013 Paris",
        latitude=48.85363,
        longitude=2.36359,
    ),
    Facility(
        code="273",
        name="Niox",
        address="12 quai Saint-Exupéry, 75016 Paris",
        latitude=48.83724,
        longitude=2.26436,
    ),
    Facility(
        code="281",
        name="Château des Rentiers",
        address="184 rue du Château des Rentiers, 75013 Paris",
        latitude=48.83877,
        longitude=2.30475,
    ),
    Facility(
        code="293",
        name="Max Rousié",
        address="28 rue André Bréchet, 75017 Paris",
        latitude=48.85686,
        longitude=2.39154,
    ),
    Facility(
        code="302",
        name="Paul Barruel",
        address="24 rue Paul Barruel, 75015 Paris",
        latitude=48.89972,
        longitude=2.35197,
    ),
    Facility(
        code="303",
        name="Sablonnière",
        address="62 rue Cambronne, 75015 Paris",
        latitude=48.83982,
        longitude=2.35771,
    ),
    Facility(
        code="305",
        name="Sept Arpents",
        address="9 rue des Sept Arpents, 75019 Paris",
        latitude=48.8625,
        longitude=2.41201,
    ),
    Facility(
        code="320",
        name="Thiéré",
        address="9-11 passage Thiéré, 75011 Paris",
        latitude=48.82031,
        longitude=2.35382,
    ),
    Facility(
        code="327",
        name="Alain Mimoun",
        address="15 rue de la Nouvelle Calédonie, 75012 Paris",
        latitude=48.87569,
        longitude=2.24347,
    ),
    Facility(
        code="330",
        name="Valeyre",
        address="24 rue de Rochechouart, 75009 Paris",
        latitude=48.88891,
        longitude=2.29611,
    ),
    Facility(
        code="428",
        name="Cordelières",
        address="35 rue des Cordelières, 75013 Paris",
        latitude=48.8489,
        longitude=2.28493,
    ),
    Facility(
        code="429",
        name="Henry de Montherlant",
        address="30-32 Boulevard Lannes, 75016 Paris",
        latitude=48.82653,
        longitude=2.30001,
    ),
    Facility(
        code="497",
        name="Jules Ladoumègue",
        address="39 rue des Petits Ponts, 75019 Paris",
        latitude=48.84397,
        longitude=2.30206,
    ),
    Facility(
        code="529",
        name="Puteaux",
        address="1 allée des sports, 92800 Puteaux",
        latitude=48.88955,
        longitude=2.39877,
    ),
    Facility(
        code="545",
        name="Neuve Saint Pierre",
        address="5-7 rue Neuve-Saint-Pierre, 75004 Paris",
        latitude=48.83265,
        longitude=2.2767,
    ),
    Facility(
        code="560",
        name="Bobigny",
        address="40-102 avenue de la Division Leclerc, 93000 Bobigny",
        latitude=48.85377,
        longitude=2.37378,
    ),
    Facility(
        code="567",
        name="Halle Fret",
        address="47 rue des Cheminots, 75018 Paris",
        latitude=48.87793,
        longitude=2.34509,
    ),
]


@router.get("", response_model=list[Facility])
def list_facilities() -> list[Facility]:
    """Get all tennis facilities."""
    return FACILITIES
