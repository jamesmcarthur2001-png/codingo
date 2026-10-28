# midnight_models
Shared models of midnight-api. Models only (pydantic is fine).
- No functions, no validators, no raising errors. Validation happens in evermore, on the real data.
- Export every new model from the package's __init__.py.
- No tests here; the models are tested through the services that use them.
