"""Facilities API routes."""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/facilities", tags=["facilities"])


class Facility(BaseModel):
    """Tennis facility."""

    code: str
    name: str
    address: str
    indoor_courts: int
    outdoor_courts: int


# Paris Tennis facilities (based on tennis.paris.fr)
FACILITIES = [
    Facility(
        code="atlantique",
        name="Centre Sportif Atlantique",
        address="30 rue de l'Amiral Mouchez, 75013 Paris",
        indoor_courts=3,
        outdoor_courts=2,
    ),
    Facility(
        code="candie",
        name="Centre Sportif Candie",
        address="4 rue de Candie, 75011 Paris",
        indoor_courts=2,
        outdoor_courts=0,
    ),
    Facility(
        code="carpentier",
        name="Centre Sportif Carpentier",
        address="81 boulevard Masséna, 75013 Paris",
        indoor_courts=4,
        outdoor_courts=0,
    ),
    Facility(
        code="championnet",
        name="Centre Sportif Championnet",
        address="9 rue Jean Cocteau, 75018 Paris",
        indoor_courts=3,
        outdoor_courts=0,
    ),
    Facility(
        code="charles_moureu",
        name="Centre Sportif Charles Moureu",
        address="17 avenue Edison, 75013 Paris",
        indoor_courts=2,
        outdoor_courts=2,
    ),
    Facility(
        code="elisabeth",
        name="Centre Sportif Elisabeth",
        address="7-15 avenue Paul Appell, 75014 Paris",
        indoor_courts=6,
        outdoor_courts=12,
    ),
    Facility(
        code="georges_hebert",
        name="Centre Sportif Georges Hébert",
        address="2 rue du Commandant Schloesing, 75016 Paris",
        indoor_courts=3,
        outdoor_courts=6,
    ),
    Facility(
        code="henry_de_montherlant",
        name="Centre Sportif Henry de Montherlant",
        address="32 boulevard Lannes, 75016 Paris",
        indoor_courts=4,
        outdoor_courts=4,
    ),
    Facility(
        code="jean_bouin",
        name="Centre Sportif Jean Bouin",
        address="20-40 avenue du Général Sarrail, 75016 Paris",
        indoor_courts=8,
        outdoor_courts=0,
    ),
    Facility(
        code="jessaint",
        name="Centre Sportif Jessaint",
        address="41 rue de Jessaint, 75018 Paris",
        indoor_courts=2,
        outdoor_courts=0,
    ),
    Facility(
        code="la_faluere",
        name="Centre Sportif La Faluère",
        address="2 route de la Pyramide, 75012 Paris",
        indoor_courts=2,
        outdoor_courts=8,
    ),
    Facility(
        code="leo_lagrange",
        name="Centre Sportif Léo Lagrange",
        address="68 boulevard Poniatowski, 75012 Paris",
        indoor_courts=4,
        outdoor_courts=6,
    ),
    Facility(
        code="louis_lumiere",
        name="Centre Sportif Louis Lumière",
        address="30 rue Louis Lumière, 75020 Paris",
        indoor_courts=3,
        outdoor_courts=2,
    ),
    Facility(
        code="marx_dormoy",
        name="Centre Sportif Marx Dormoy",
        address="146 rue Marx Dormoy, 75018 Paris",
        indoor_courts=2,
        outdoor_courts=0,
    ),
    Facility(
        code="poissonniers",
        name="Centre Sportif Poissonniers",
        address="2 rue Jean Cocteau, 75018 Paris",
        indoor_courts=3,
        outdoor_courts=0,
    ),
    Facility(
        code="porte_de_la_plaine",
        name="Centre Sportif Porte de la Plaine",
        address="13 rue du Général Guillaumat, 75015 Paris",
        indoor_courts=4,
        outdoor_courts=0,
    ),
    Facility(
        code="suzanne_lenglen",
        name="Centre Sportif Suzanne Lenglen",
        address="2 rue Louis Armand, 75015 Paris",
        indoor_courts=10,
        outdoor_courts=14,
    ),
]


@router.get("", response_model=list[Facility])
def list_facilities() -> list[Facility]:
    """List all available tennis facilities."""
    return FACILITIES


@router.get("/{code}", response_model=Facility)
def get_facility(code: str) -> Facility:
    """Get a specific facility by code."""
    for facility in FACILITIES:
        if facility.code == code:
            return facility
    from fastapi import HTTPException, status

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Facility not found")
