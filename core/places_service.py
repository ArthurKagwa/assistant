"""
Google Places API service for location-based recommendations.
Makes Kabanda 'the plug for cool hangouts'.
"""
import os
import logging
from typing import Dict, Any, List, Optional, Tuple
import googlemaps
from django.core.cache import cache
from django.conf import settings

logger = logging.getLogger(__name__)


class PlacesService:
    """Service for finding cool places using Google Places API."""
    
    def __init__(self):
        """Initialize the Places service with Google API."""
        self.api_key = getattr(settings, 'GOOGLE_NEW_PLACES_API', None)
        if not self.api_key:
            raise ValueError("GOOGLE_NEW_PLACES_API not configured in settings")
        
        self.gmaps = googlemaps.Client(key=self.api_key)
        self.default_radius = 5000  # 5km default search radius
    
    def search_nearby(
        self, 
        query: str, 
        lat: float, 
        lng: float, 
        radius: int = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Search for places near given coordinates.
        
        Args:
            query: Search query (e.g., "cool restaurant", "trendy bar")
            lat: Latitude
            lng: Longitude
            radius: Search radius in meters (default: 5000)
            limit: Maximum number of results (default: 5)
        
        Returns:
            List of place dictionaries with name, address, rating, etc.
        """
        try:
            # Check cache first
            cache_key = f"places_{lat}_{lng}_{query}_{radius or self.default_radius}"
            cached_results = cache.get(cache_key)
            if cached_results:
                logger.info(f"Returning cached results for: {query}")
                return cached_results[:limit]
            
            # Search using Google Places API
            location = (lat, lng)
            radius = radius or self.default_radius
            
            logger.info(f"Searching for '{query}' near ({lat}, {lng}) within {radius}m")
            
            # Use places_nearby for location-based search
            results = self.gmaps.places_nearby(
                location=location,
                radius=radius,
                keyword=query,
                type='establishment'  # General establishment type
            )
            
            places = []
            for place in results.get('results', [])[:limit]:
                place_info = {
                    'place_id': place.get('place_id'),
                    'name': place.get('name'),
                    'address': place.get('vicinity'),
                    'rating': place.get('rating'),
                    'total_ratings': place.get('user_ratings_total'),
                    'price_level': place.get('price_level'),  # 0-4 scale
                    'types': place.get('types', []),
                    'location': {
                        'lat': place.get('geometry', {}).get('location', {}).get('lat'),
                        'lng': place.get('geometry', {}).get('location', {}).get('lng')
                    },
                    'is_open': place.get('opening_hours', {}).get('open_now')
                }
                places.append(place_info)
            
            # Sort by rating (highest first) to give best recommendations
            places.sort(key=lambda x: (x.get('rating') or 0), reverse=True)
            
            # Cache for 1 hour
            cache.set(cache_key, places, timeout=3600)
            
            logger.info(f"Found {len(places)} places for '{query}'")
            return places
            
        except Exception as e:
            logger.error(f"Error searching places: {e}", exc_info=True)
            return []
    
    def geocode_location(self, location_str: str) -> Optional[Tuple[float, float]]:
        """
        Convert location string to coordinates using geocoding.
        
        Args:
            location_str: Location description (e.g., "Kampala", "near Acacia Mall")
        
        Returns:
            Tuple of (latitude, longitude) or None if not found
        """
        try:
            # Check cache first
            cache_key = f"geocode_{location_str}"
            cached_coords = cache.get(cache_key)
            if cached_coords:
                return cached_coords
            
            logger.info(f"Geocoding location: {location_str}")
            
            results = self.gmaps.geocode(location_str)
            if results:
                location = results[0]['geometry']['location']
                coords = (location['lat'], location['lng'])
                
                # Cache for 24 hours
                cache.set(cache_key, coords, timeout=86400)
                
                logger.info(f"Geocoded '{location_str}' to {coords}")
                return coords
            
            logger.warning(f"No geocoding results for: {location_str}")
            return None
            
        except Exception as e:
            logger.error(f"Error geocoding location: {e}", exc_info=True)
            return None
    
    def get_top_recommendations(
        self, 
        query: str, 
        lat: float, 
        lng: float, 
        limit: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Get top curated recommendations for a query.
        Filters for best ratings and most reviews.
        
        Args:
            query: What to search for
            lat: Latitude
            lng: Longitude
            limit: Number of top recommendations (default: 3)
        
        Returns:
            List of top-rated places
        """
        places = self.search_nearby(query, lat, lng, limit=limit * 2)
        
        # Filter for quality: rating >= 4.0 and at least 50 reviews
        quality_places = [
            p for p in places 
            if p.get('rating', 0) >= 4.0 and p.get('total_ratings', 0) >= 50
        ]
        
        # If we filtered too aggressively, fallback to just top-rated
        if len(quality_places) < limit:
            quality_places = places[:limit]
        
        return quality_places[:limit]
    
    def get_place_details(self, place_id: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a specific place.
        
        Args:
            place_id: Google Place ID
        
        Returns:
            Detailed place information or None
        """
        try:
            # Check cache
            cache_key = f"place_details_{place_id}"
            cached_details = cache.get(cache_key)
            if cached_details:
                return cached_details
            
            result = self.gmaps.place(place_id)
            details = result.get('result', {})
            
            # Cache for 1 day
            cache.set(cache_key, details, timeout=86400)
            
            return details
            
        except Exception as e:
            logger.error(f"Error getting place details: {e}", exc_info=True)
            return None
    
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
