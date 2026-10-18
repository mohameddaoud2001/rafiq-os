from typing import List, Protocol

from rafiq.rag.madhhab_stores import Passage


class Retriever(Protocol):
    def search(
        self, query: str, madhhab: str = None, limit: int = 5, verified_only: bool = False
    ) -> List[Passage]: ...


class MadhhabRetriever:
    def search(
        self, query: str, madhhab: str = None, limit: int = 5, verified_only: bool = False
    ) -> List[Passage]:
        from rafiq.rag.madhhab_stores import search_all_madhhabs, search_passages

        if madhhab:
            return search_passages(madhhab, query, limit=limit, verified_only=verified_only)
        # search all, flatten
        all_res = search_all_madhhabs(query, limit_per=limit, verified_only=verified_only)
        flat = []
        for lst in all_res.values():
            flat.extend(lst)
        return flat[: limit * 4]
