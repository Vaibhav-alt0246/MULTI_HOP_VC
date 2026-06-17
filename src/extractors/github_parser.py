import requests
import networkx as nx
import json
import os

def fetch_dependencies(url):
    """Fetches and parses a package.json file from a raw GitHub URL."""
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        deps = data.get('dependencies', {})
        dev_deps = data.get('devDependencies', {})
        return {**deps, **dev_deps}
    except Exception as e:
        print(f"   [Warning] Skipping path (or file not found): {url.split('main/')[-1]}")
        return {}

def build_scaled_graph(repo_list):
    """Ingests a list of repositories and builds a single unified knowledge graph."""
    G = nx.DiGraph()
    
    print(f"=== Beginning Big Data Extraction for {len(repo_list)} Repositories ===\n")
    
    for repo in repo_list:
        owner = repo["owner"]
        name = repo["name"]
        repo_id = f"{owner}/{name}"
        
        print(f"Processing Repository: {repo_id}...")
        G.add_node(repo_id, type="Repository", owner=owner, name=name)
        
        base_raw_url = f"https://raw.githubusercontent.com/{owner}/{name}/main"
        
        # Look for different architectural layers based on common MERN/Node setups
        paths_to_try = {
            "Backend": [f"{base_raw_url}/backend/package.json", f"{base_raw_url}/server/package.json"],
            "Frontend": [f"{base_raw_url}/frontend/package.json", f"{base_raw_url}/client/package.json"],
            "Root_Layer": [f"{base_raw_url}/package.json"]
        }
        
        for layer_name, urls in paths_to_try.items():
            for url in urls:
                deps = fetch_dependencies(url)
                if deps:
                    layer_id = f"{repo_id}::{layer_name}"
                    G.add_node(layer_id, type="Architecture_Layer", name=layer_name)
                    G.add_edge(repo_id, layer_id, relationship="CONTAINS")
                    
                    for lib, version in deps.items():
                        # Crucial Big Data step: Libraries are shared globally among repos!
                        G.add_node(lib, type="Library")
                        G.add_edge(layer_id, lib, relationship="DEPENDS_ON", version=version)
                    break # Stop checking alternative URLs for this layer if one worked
                    
    return G

def export_graph(G, output_path):
    data = nx.node_link_data(G)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=4)
    print("\n" + "="*40)
    print(f"Success! Scaled Graph exported to {output_path}")
    print(f"Total Combined Nodes: {G.number_of_nodes()}")
    print(f"Total Combined Edges: {G.number_of_edges()}")
    print("="*40)

if __name__ == "__main__":
    # List of target MERN/Fullstack repositories to construct your big dataset sandbox
    target_startups_repos = [
        {"owner": "Shubham-cyber-prog", "name": "MERN-Expense-Tracker"},
        {"owner": "BhattAsim", "name": "Mern-Stack-Project-Management-Tool"},
        {"owner": "bradtraversy", "name": "support-desk"}
    ]
    
    scaled_dependency_graph = build_scaled_graph(target_startups_repos)
    export_graph(scaled_dependency_graph, "data/processed/github_graph.json")