from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.tree import DecisionTreeClassifier


class DecisionForestClassifier(ClassifierMixin, BaseEstimator):
    """A small probability-capable forest that avoids optional ensemble DLLs."""

    def __init__(
        self,
        n_estimators: int = 200,
        max_depth: int | None = 12,
        min_samples_leaf: int = 10,
        class_weight: str | dict[Any, float] | None = "balanced",
        bootstrap: bool = True,
        splitter: str = "best",
        random_state: int | None = 42,
    ) -> None:
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.min_samples_leaf = min_samples_leaf
        self.class_weight = class_weight
        self.bootstrap = bootstrap
        self.splitter = splitter
        self.random_state = random_state

    def fit(self, x: Any, y: Any) -> DecisionForestClassifier:
        """Fit independent feature-randomized trees on reproducible samples."""

        if self.n_estimators < 1:
            raise ValueError("n_estimators must be at least 1")
        target = np.asarray(y)
        self.classes_ = np.unique(target)
        if len(self.classes_) != 2:
            raise ValueError("DecisionForestClassifier requires two target classes")
        rng = np.random.default_rng(self.random_state)
        row_count = len(target)
        self.estimators_: list[DecisionTreeClassifier] = []
        for _ in range(self.n_estimators):
            seed = int(rng.integers(0, np.iinfo(np.int32).max))
            indices = rng.integers(0, row_count, row_count) if self.bootstrap else np.arange(row_count)
            tree = DecisionTreeClassifier(
                splitter=self.splitter,
                max_depth=self.max_depth,
                min_samples_leaf=self.min_samples_leaf,
                max_features="sqrt",
                class_weight=self.class_weight,
                random_state=seed,
            )
            tree.fit(x[indices], target[indices])
            self.estimators_.append(tree)
        self.n_features_in_ = self.estimators_[0].n_features_in_
        return self

    def predict_proba(self, x: Any) -> np.ndarray:
        """Average tree probabilities into one forest probability."""

        probabilities = np.zeros((x.shape[0], len(self.classes_)), dtype=float)
        for tree in self.estimators_:
            tree_probabilities = tree.predict_proba(x)
            for tree_index, label in enumerate(tree.classes_):
                forest_index = int(np.where(self.classes_ == label)[0][0])
                probabilities[:, forest_index] += tree_probabilities[:, tree_index]
        return probabilities / len(self.estimators_)

    def predict(self, x: Any) -> np.ndarray:
        """Return the class with the greatest averaged probability."""

        return self.classes_[np.argmax(self.predict_proba(x), axis=1)]
