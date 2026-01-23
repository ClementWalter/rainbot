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


# All 44 Paris Tennis facilities with geocoded coordinates
# Coordinates verified against OpenStreetMap/Google Maps
FACILITIES = [
    Facility(
        code="2",
        name="Amandiers",
        address="8 rue Louis Delgrès, 75020 Paris",
        latitude=48.8645,
        longitude=2.3858,
    ),
    Facility(
        code="12",
        name="Atlantique",
        address="25 allée du Capitaine Dronne, 75015 Paris",
        latitude=48.8321,
        longitude=2.2863,
    ),
    Facility(
        code="15",
        name="Philippe Auguste",
        address="108 avenue Philippe Auguste, 75011 Paris",
        latitude=48.8545,
        longitude=2.3940,
    ),
    Facility(
        code="23",
        name="Porte de Bagnolet",
        address="72 rue Louis Lumière, 75020 Paris",
        latitude=48.8690,
        longitude=2.4120,
    ),
    Facility(
        code="53",
        name="Candie",
        address="11 rue Candie, 75011 Paris",
        latitude=48.8565,
        longitude=2.3818,
    ),
    Facility(
        code="58",
        name="Carnot",
        address="26 boulevard Carnot, 75012 Paris",
        latitude=48.8395,
        longitude=2.4150,
    ),
    Facility(
        code="60",
        name="Georges Carpentier",
        address="5 Place de Port au Prince, 75013 Paris",
        latitude=48.8180,
        longitude=2.3580,
    ),
    Facility(
        code="67",
        name="Jesse Owens",
        address="172 rue Championnet, 75018 Paris",
        latitude=48.8950,
        longitude=2.3380,
    ),
    Facility(
        code="79",
        name="Reims - Asnières",
        address="34 boulevard de Reims, 75017 Paris",
        latitude=48.8920,
        longitude=2.2900,
    ),
    Facility(
        code="81",
        name="Courcelles",
        address="211 rue de Courcelles, 75017 Paris",
        latitude=48.8870,
        longitude=2.2930,
    ),
    Facility(
        code="85",
        name="Aurelle de Paladines",
        address="10 rue Parmentier, 92200 Neuilly sur Seine",
        latitude=48.8845,
        longitude=2.2645,
    ),
    Facility(
        code="92",
        name="Bertrand Dauvin",
        address="12 rue René Binet, 75018 Paris",
        latitude=48.8970,
        longitude=2.3455,
    ),
    Facility(
        code="98",
        name="Docteurs Déjerine",
        address="32-36 rue des Docteurs Déjerine, 75020 Paris",
        latitude=48.8610,
        longitude=2.4085,
    ),
    Facility(
        code="109",
        name="Dunois",
        address="70 rue Dunois, 75013 Paris",
        latitude=48.8268,
        longitude=2.3630,
    ),
    Facility(
        code="120",
        name="Elisabeth",
        address="7 avenue Paul Appell, 75014 Paris",
        latitude=48.8220,
        longitude=2.3265,
    ),
    Facility(
        code="126",
        name="La Faluère",
        address="route de la Pyramide, 75012 Paris",
        latitude=48.8380,
        longitude=2.4500,
    ),
    Facility(
        code="155",
        name="Jandelle",
        address="15-17 cité Jandelle, 75019 Paris",
        latitude=48.8780,
        longitude=2.3910,
    ),
    Facility(
        code="174",
        name="Léo Lagrange",
        address="68 boulevard Poniatowski, 75012 Paris",
        latitude=48.8365,
        longitude=2.4105,
    ),
    Facility(
        code="188",
        name="Suzanne Lenglen",
        address="2 rue Louis Armand, 75015 Paris",
        latitude=48.8310,
        longitude=2.2720,
    ),
    Facility(
        code="198",
        name="Louis Lumière",
        address="30 rue Louis Lumière, 75020 Paris",
        latitude=48.8680,
        longitude=2.4100,
    ),
    Facility(
        code="218",
        name="Moureu - Baudricourt",
        address="17 avenue Edison, 75013 Paris",
        latitude=48.8265,
        longitude=2.3695,
    ),
    Facility(
        code="220",
        name="René et André Mourlon",
        address="19 rue Gaston de Caillavet, 75015 Paris",
        latitude=48.8475,
        longitude=2.2850,
    ),
    Facility(
        code="233",
        name="Croix Nivert",
        address="107 rue de la Croix Nivert, 75015 Paris",
        latitude=48.8455,
        longitude=2.2985,
    ),
    Facility(
        code="240",
        name="Edouard Pailleron",
        address="24 rue Edouard Pailleron, 75019 Paris",
        latitude=48.8800,
        longitude=2.3775,
    ),
    Facility(
        code="258",
        name="Rigoulot - La Plaine",
        address="18 avenue de la Porte de Brancion, 75015 Paris",
        latitude=48.8280,
        longitude=2.3020,
    ),
    Facility(
        code="264",
        name="Poissonniers",
        address="2 rue Jean Cocteau, 75018 Paris",
        latitude=48.8930,
        longitude=2.3500,
    ),
    Facility(
        code="267",
        name="Poliveau",
        address="39bis rue de Poliveau, 75005 Paris",
        latitude=48.8395,
        longitude=2.3545,
    ),
    Facility(
        code="272",
        name="Poterne des Peupliers",
        address="17 rue Max Jacob, 75013 Paris",
        latitude=48.8185,
        longitude=2.3580,
    ),
    Facility(
        code="273",
        name="Niox",
        address="12 quai Saint-Exupéry, 75016 Paris",
        latitude=48.8515,
        longitude=2.2640,
    ),
    Facility(
        code="281",
        name="Château des Rentiers",
        address="184 rue du Château des Rentiers, 75013 Paris",
        latitude=48.8245,
        longitude=2.3665,
    ),
    Facility(
        code="293",
        name="Max Rousié",
        address="28 rue André Bréchet, 75017 Paris",
        latitude=48.8945,
        longitude=2.3135,
    ),
    Facility(
        code="302",
        name="Paul Barruel",
        address="24 rue Paul Barruel, 75015 Paris",
        latitude=48.8385,
        longitude=2.3010,
    ),
    Facility(
        code="303",
        name="Sablonnière",
        address="62 rue Cambronne, 75015 Paris",
        latitude=48.8465,
        longitude=2.3020,
    ),
    Facility(
        code="305",
        name="Sept Arpents",
        address="9 rue des Sept Arpents, 75019 Paris",
        latitude=48.8840,
        longitude=2.3995,
    ),
    Facility(
        code="320",
        name="Thiéré",
        address="9-11 passage Thiéré, 75011 Paris",
        latitude=48.8545,
        longitude=2.3755,
    ),
    Facility(
        code="327",
        name="Alain Mimoun",
        address="15 rue de la Nouvelle Calédonie, 75012 Paris",
        latitude=48.8405,
        longitude=2.4240,
    ),
    Facility(
        code="330",
        name="Valeyre",
        address="24 rue de Rochechouart, 75009 Paris",
        latitude=48.8795,
        longitude=2.3455,
    ),
    Facility(
        code="428",
        name="Cordelières",
        address="35 rue des Cordelières, 75013 Paris",
        latitude=48.8325,
        longitude=2.3510,
    ),
    Facility(
        code="429",
        name="Henry de Montherlant",
        address="30-32 Boulevard Lannes, 75016 Paris",
        latitude=48.8710,
        longitude=2.2700,
    ),
    Facility(
        code="497",
        name="Jules Ladoumègue",
        address="39 rue des Petits Ponts, 75019 Paris",
        latitude=48.8960,
        longitude=2.3900,
    ),
    Facility(
        code="529",
        name="Puteaux",
        address="1 allée des sports, 92800 Puteaux",
        latitude=48.8845,
        longitude=2.2370,
    ),
    Facility(
        code="545",
        name="Neuve Saint Pierre",
        address="5-7 rue Neuve-Saint-Pierre, 75004 Paris",
        latitude=48.8545,
        longitude=2.3605,
    ),
    Facility(
        code="560",
        name="Bobigny",
        address="40-102 avenue de la Division Leclerc, 93000 Bobigny",
        latitude=48.9085,
        longitude=2.4380,
    ),
    Facility(
        code="567",
        name="Halle Fret",
        address="47 rue des Cheminots, 75018 Paris",
        latitude=48.8965,
        longitude=2.3615,
    ),
]


@router.get("", response_model=list[Facility])
def list_facilities() -> list[Facility]:
    """Get all tennis facilities."""
    return FACILITIES
