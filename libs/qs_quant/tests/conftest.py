from hypothesis import settings

# 200 examples per property (C-NFR-04, Lane C guide §14); derandomized so CI is reproducible
settings.register_profile("qs", max_examples=200, derandomize=True, deadline=None)
settings.load_profile("qs")
