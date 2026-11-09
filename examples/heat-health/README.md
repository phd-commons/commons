# Worked example: heat and hospital admissions (fictional)

An invented thesis in public health, used to show how Commons turns a research proposal into testable
propositions, rival explanations and a daily feed. It is not anyone's real project.

- `thesis.yaml`: four propositions and three rivals, each with what would support it and what would count against it.
- `sources.yaml`: queries for the daily sweep, including two aimed at the rivals.

Try it with the demo provider (no models needed):

```
commons init ~/commons-demo --preset demo
cp thesis.yaml sources.yaml ~/commons-demo/
cd ~/commons-demo
commons sweep            # needs internet; pulls recent open-access work from OpenAlex and Crossref
commons thesis
commons serve            # http://127.0.0.1:8700
```

With the demo provider the screening and answers are mechanical stand-ins. Switch to a real preset to see the
real thing.
