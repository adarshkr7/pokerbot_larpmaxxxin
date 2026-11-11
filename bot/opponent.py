"""Opponent model. F01 ships the neutral stub; F12 replaces it (same interface)."""


class OppModel:
    PRIORS = {"vpip": 0.5, "pfr": 0.2, "fold_to_bet": 0.4, "aggression": 1.0}

    def observe_action(self, *args, **kwargs):
        pass

    def observe_showdown(self, *args, **kwargs):
        pass

    def stat(self, name):
        return self.PRIORS.get(name, 0.0)

    def archetype_weights(self):
        return {"neutral": 1.0}

    def range_weights(self, *args, **kwargs):
        return None
