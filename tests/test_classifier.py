"""Unit tests for the content classifier heuristics."""

import pytest

from app.feed.classifier import classify_article


@pytest.mark.parametrize(
    "title,text,expected",
    [
        # --- Recipes (Spanish) ---
        (
            "Receta de paella valenciana",
            "Para hacer esta paella necesitará los siguientes ingredientes: arroz, pollo...",
            "non_news",
        ),
        (
            "Cómo preparar una tortilla española",
            "Ingredientes: 6 huevos, 500 g de patatas. Tiempo de preparación: 20 minutos.",
            "non_news",
        ),
        (
            "El mejor gazpacho del verano",
            "Ingredientes: tomates, pepino, pimiento. Cucharada de aceite. Porciones: 4.",
            "non_news",
        ),
        # --- Recipes (English) ---
        (
            "How to make banana bread",
            "Ingredients: 3 ripe bananas, 1/3 cup melted butter. Preheat oven to 350°F.",
            "non_news",
        ),
        (
            "Classic chocolate chip cookies",
            "Prep time: 15 minutes. Servings: 24 cookies. Ingredients: 2 cups flour...",
            "non_news",
        ),
        # --- Horoscopes ---
        (
            "Horóscopo de hoy",
            "Aries: buenas noticias en el trabajo. Tauro: cuida tu salud. Géminis: amor.",
            "non_news",
        ),
        (
            "Your daily horoscope for March",
            "Aries: exciting opportunities. Taurus: focus on finances. Gemini: social life.",
            "non_news",
        ),
        # --- Strong title signals alone ---
        (
            "Receta de tarta de queso al horno",
            "",
            "non_news",
        ),
        (
            "Horoscope for the week of March 24",
            "",
            "non_news",
        ),
        # --- Classifieds ---
        (
            "Apartamento en Barcelona",
            "Se alquila piso de 3 habitaciones. Precio negociable. Contactar por whatsapp.",
            "non_news",
        ),
        # --- Legitimate news (should NOT be flagged) ---
        (
            "El Govern anuncia un pla per reduir emissions de CO2",
            "El president ha presentat un ambiciós pla climàtic per als propers cinc anys.",
            "news",
        ),
        (
            "Barça beats Real Madrid in El Clásico",
            "Barcelona secured a 3-1 victory over Real Madrid at Camp Nou on Sunday.",
            "news",
        ),
        (
            "Inflation hits 3.2% in February, central bank responds",
            "Consumer prices rose 3.2 percent year-on-year in February, according to statistics.",
            "news",
        ),
        (
            "Scientists discover new species in Amazon rainforest",
            "Researchers from the University of São Paulo announced the discovery of a new amphibian species.",
            "news",
        ),
        # --- Edge: single signal should NOT trigger ---
        (
            "Restaurant review: the best paella in Valencia",
            "The chef uses fresh ingredients and local rice for an authentic experience.",
            "news",
        ),
    ],
)
def test_classify_article(title: str, text: str, expected: str) -> None:
    assert classify_article(title, text) == expected
