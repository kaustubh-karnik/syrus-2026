class HybridGraphRetriever:
    """GraphRAG/embedding retrieval has been disabled in this codebase."""

    def retrieve(self, state: dict) -> dict:
        _ = state
        return {
            "retrieval_context": {
                "query": "",
                "seed_files": [],
                "graph_edges": [],
                "ranked_files": [],
                "context_text": "",
            },
            "retrieved_files": [],
            "retrieved_code": "",
            "status": "disabled",
            "error": "GraphRAG embedding retrieval is disabled",
        }
