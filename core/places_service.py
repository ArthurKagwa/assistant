import os
import logging
import requests
from typing import Dict, Any, List, Optional, Tuple
from django.core.cache import cache
from django.conf import settings

logger = logging.getLogger(__name__)


class PlacesService:
    """Service for finding cool places using Google Places API (New) v1."""
    
    def __init__(self):
        """Initialize the Places service with Google API."""
        self.api_key = getattr(settings, 'GOOGLE_NEW_PLACES_API', None)
        if not self.api_key:
            raise ValueError("GOOGLE_NEW_PLACES_API not configured in settings")
        
        self.v1_url = "https://places.googleapis.com/v1/places"
        self.default_radius = 5000.0  # 5km default search radius
    
    def search_nearby(
        self, 
        query: str, 
        lat: float, 
        lng: float, 
        radius: float = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Search for places near given coordinates using Places API (New) v1.
        """
        try:
            # Check cache first
            cache_key = f"places_v1_{lat}_{lng}_{query}_{radius or self.default_radius}"
            cached_results = cache.get(cache_key)
            if cached_results:
                logger.info(f"Returning cached v1 results for: {query}")
                return cached_results[:limit]
            
            headers = {
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self.api_key,
                "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.rating,places.userRatingCount,places.priceLevel,places.types,places.location"
            }
            
            # The New API separates searchByText and searchNearby
            # For "cool restaurant nearby", searchByText is often better as it handles keywords
            
            search_url = f"{self.v1_url}:searchText"
            payload = {
                "textQuery": query,
                "locationBias": {
                    "circle": {
                        "center": {"latitude": lat, "longitude": lng},
                        "radius": radius or self.default_radius
                    }
                },
                "maxResultCount": limit * 2
            }
            
            logger.info(f"Searching v1 for '{query}' near ({lat}, {lng})")
            
            response = requests.post(search_url, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            results = data.get('places', [])
            
            places = []
            for p in results:
                # Map v1 response to our internal format
                place_info = {
                    'place_id': p.get('id'),
                    'name': p.get('displayName', {}).get('text'),
                    'address': p.get('formattedAddress'),
                    'rating': p.get('rating'),
                    'total_ratings': p.get('userRatingCount'),
                    'price_level': p.get('priceLevel'),
                    'types': p.get('types', []),
                    'location': {
                        'lat': p.get('location', {}).get('latitude'),
                        'lng': p.get('location', {}).get('longitude')
                    }
                }
                places.append(place_info)
            
            # Sort by quality: rating * log(total_ratings) is a good proxy for "coolness"
            import math
            places.sort(
                key=lambda x: (x.get('rating') or 0) * math.log10(max(x.get('total_ratings') or 1, 10)), 
                reverse=True
            )
            
            # Cache for 1 hour
            cache.set(cache_key, places, timeout=3600)
            
            return places[:limit]
            
        except Exception as e:
            logger.error(f"Error searching v1 places: {e}", exc_info=True)
            return []
    
    def geocode_location(self, location_str: str) -> Optional[Tuple[float, float]]:
        """
        Geocode using the new API isn't a direct endpoint in Places v1, 
        but we can use searchText and take the first result's location.
        """
        try:
            cache_key = f"geocode_v1_{location_str}"
            cached_coords = cache.get(cache_key)
            if cached_coords:
                return cached_coords
            
            headers = {
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self.api_key,
                "X-Goog-FieldMask": "places.location"
            }
            
            payload = {
                "textQuery": location_str,
                "maxResultCount": 1
            }
            
            response = requests.post(f"{self.v1_url}:searchText", headers=headers, json=payload, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            places = data.get('places', [])
            
            if places:
                loc = places[0].get('location', {})
                coords = (loc.get('latitude'), loc.get('longitude'))
                if coords[0] and coords[1]:
                    cache.set(cache_key, coords, timeout=86400)
                    return coords
            
            return None
        except Exception as e:
            logger.error(f"Error geocoding v1: {e}")
            return None

    def get_top_recommendations(
        self, 
        query: str, 
        lat: float, 
        lng: float, 
        limit: int = 3
    ) -> List[Dict[str, Any]]:
        """Get top quality recommendations."""
        return self.search_nearby(query, lat, lng, limit=limit)
    
    def get_place_details(self, place_id: str) -> Optional[Dict[str, Any]]:
        """Get details for a specific place using v1."""
        try:
            headers = {
                "X-Goog-Api-Key": self.api_key,
                "X-Goog-FieldMask": "*" # Get all fields for details
            }
            
            response = requests.get(f"{self.v1_url}/{place_id}", headers=headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error getting v1 details: {e}")
            return None

    def format_place_for_task(self, place: Dict[str, Any]) -> str:
        """Format a place into a friendly task description."""
        name = place.get('name', 'Unknown place')
        rating = place.get('rating')
        address = place.get('address', '')
        
        description = f"{name}"
        if rating:
            stars = "⭐" * int(rating or 0)
            description += f" {stars} ({rating})"
        if address:
            description += f" - {address}"
        
        return description

    
    def format_place_for_task(self, place: Dict[str, Any]) -> str:
        """
        Format a place into a friendly task description.
        
        Args:
            place: Place dictionary from search results
        
        Returns:
            Formatted string for task
        """
        name = place.get('name', 'Unknown place')
        rating = place.get('rating')
        address = place.get('address', '')
        
        description = f"{name}"
        if rating:
            stars = "⭐" * int(rating)
            description += f" {stars} ({rating})"
        if address:
            description += f" - {address}"
        
        return description


# Singleton instance
_places_service = None

def get_places_service() -> PlacesService:
    """Get or create Places service singleton."""
    global _places_service
    if _places_service is None:
        _places_service = PlacesService()
    return _places_service
