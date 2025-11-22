import json
from typing import Any, Dict

import requests

ENDPOINT = "https://rickandmortyapi.com/graphql"

def testing_query():
    query = """
      query {
        locations(page: 1) {
          info { count pages next prev }
          results {
            id
            name
            type
            dimension
            residents { id name }
          }
        }
      }
    """

    # Send POST request
    response = requests.post(
        ENDPOINT,
        json={'query': query}
    )

    # Check the response
    if response.status_code == 200:
        data = response.json()
        print(json.dumps(data, indent=2))
    else:
        print(f"Query failed with status code {response.status_code}")
        print(response.text)


def query_graphql(query: str, filter: str = "") -> Dict[str, Any]:
    """Send a GraphQL query to the Rick & Morty API and return the parsed JSON response."""

    payload = {"query": query}
    if filter == "":
        payload["variables"] = {"filter":{"name":""}}
    else:
        payload["variables"] = {"filter":{"name":filter}}

    resp = requests.post(ENDPOINT, json=payload)
    #resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        # raise GraphQL errors
        raise RuntimeError(f"GraphQL returned : {data['errors']}")
    return data.get("data", {})


CHARACTERS = """
query($filter: FilterCharacter) {
  characters(page: 1, filter: $filter) {
    info { count pages next prev }
    results {
      id
      name
      status
      species
      type
      gender
      image
      origin { name }
      location { name }
    }
  }
}
"""

EPISODES = """
query($filter: FilterEpisode) {
  episodes(page: 1, filter: $filter) {
    info { count pages next prev }
    results {
      id
      name
      air_date
      episode
      characters { id name }
    }
  }
}
"""

LOCATIONS = """
query($filter: FilterLocation) {
  locations(page: 1, filter: $filter) {
    info { count pages next prev }
    results {
      id
      name
      type
      dimension
      residents { id name }
    }
  }
}
"""

def fetch(query: str, page: int = 1, filter : str = "") -> Dict[str, Any]:
    """ just get the results from the API """
    results = query_graphql(query, filter=filter)
    return results


def fetch_and_save(query: str, page: int = 1, filter : str = "") -> bool:
    """ get the results from the API and save locally to json """
    results = query_graphql(query, filter=filter)

    fnames = {LOCATIONS:"locations", CHARACTERS:"characters", EPISODES:"episodes"}

    with open(f"{fnames[query]}.json", "w") as f:
        json.dump(results, f, indent=2)