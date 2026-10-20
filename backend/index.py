"""Persistent lexical TF-IDF index (character n-grams, no local neural model).

Only load joblib indexes made by this project, never untrusted downloaded pickles.
"""

import hashlib
import json
import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from .settings import DATA


def document(p):
    fields = [
        p.get(k)
        for k in (
            "display_name",
            "name_ru",
            "name_kk",
            "name_en",
            "category",
            "subcategory_label",
            "website_description",
        )
    ]
    labels = {
        "food_drink": "кафе ресторан кофе еда тамақ кофе асхана",
        "nature": "парк прогулка серуен саябақ",
        "culture": "музей мұражай выставка",
        "sightseeing": "достопримечательность турист саяхат",
        "children": "дети ребёнок бала ойын алаңы",
        "shopping": "магазин торговый центр сауда",
    }
    fields.append(labels.get(p.get("category"), ""))
    # Template descriptions and raw key=value tags mostly repeat addresses.
    # Keep addresses out: searching Bayterek must not match every nearby address.
    if p.get("description_type") in (
        "source_text",
        "source_summary",
        "attribute_grounded_summary",
    ):
        fields.append(p.get("short_description"))
    fields.extend(p.get("aliases") or [])
    fields.extend((p.get("semantic_attributes") or [])[:25])
    for key, label in [
        ("power_outlets", "розетка қуат"),
        ("quiet_place", "тихо тыныш"),
        ("playground", "детская площадка бала"),
        ("interactive_exhibits", "интерактивный музей"),
        ("wifi_available", "Wi-Fi интернет"),
    ]:
        if p.get(key) is True:
            scope = str(p.get(key + "_scope") or "").casefold()
            if key != "quiet_place" or not any(
                w in scope for w in ["testimonial", "single", "review", "отзыв"]
            ):
                fields.append(label)
    if p.get("indoor_outdoor") in ("indoor", "outdoor", "both"):
        fields.append(
            {
                "indoor": "в помещении",
                "outdoor": "на улице",
                "both": "в помещении и на улице",
            }[p["indoor_outdoor"]]
        )
    if p.get("laptop_friendly") is True:
        fields.append("сигнал пригодности для работы с ноутбуком")
    # Attributes supported by repeated review statements (see review_signals.jsonl).
    fields.extend(p.get("_review_labels") or [])
    return " ".join(str(x) for x in fields if x)


class SearchIndex:
    backend = "tfidf"

    def __init__(self, pois):
        self.pois = pois
        self.texts = [document(p) for p in pois]
        self.fingerprint = hashlib.sha256("\n".join(self.texts).encode()).hexdigest()
        self.path = DATA / "indexes" / "tfidf.joblib"
        self._load_or_build()

    def _load_or_build(self):
        if self.path.exists():
            obj = joblib.load(self.path)
            if obj["fingerprint"] == self.fingerprint:
                self.matrix, self.vectorizer = obj["matrix"], obj["vectorizer"]
                return
        self.vectorizer = TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(2, 4),
            min_df=1,
            max_features=80000,
            sublinear_tf=True,
            dtype=np.float32,
        )
        self.matrix = self.vectorizer.fit_transform(self.texts)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        joblib.dump(
            {
                "fingerprint": self.fingerprint,
                "matrix": self.matrix,
                "vectorizer": self.vectorizer,
            },
            temp,
            compress=3,
        )
        temp.replace(self.path)

    def scores(self, query):
        if not query.strip():
            return np.zeros(len(self.pois))
        return (self.matrix @ self.vectorizer.transform([query]).T).toarray().ravel()


if __name__ == "__main__":
    from .service import City

    city = City()
    print(json.dumps({"backend": "tfidf", "documents": len(city.pois), "index": str(city.index.path)}))
