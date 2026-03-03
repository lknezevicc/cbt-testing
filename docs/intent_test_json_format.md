# Intent test JSON format

Lokacija test filea je vezana uz dialog file:

- Dialog: `<topic>/<dialog_name>.yml`
- Test JSON: `<topic>/test/<dialog_name>.json`

## Minimalni primjer

```json
[
  "Kako mogu promijeniti način dostave izvatka?",
  "Želim primati izvod e-mailom"
]
```

U ovom formatu `expected_intent` je automatski postavljen na ime dialoga (`dialog_name`).

## Prošireni primjer

```json
{
  "questions": [
    {
      "question": "Kako mogu promijeniti način dostave izvatka?",
      "expected_intent": "account_statement_change_delivery_method"
    },
    {
      "question": "Želim instant plaćanje",
      "expected_intent": "instant_payment_general_info"
    }
  ]
}
```

## Napomena

Ako `expected_intent` nije definiran po pitanju, koristi se ime dialoga iz YAML-a.

## Pokretanje na Windows PowerShell

Iz root direktorija projekta pokreni:

```powershell
.\run_intent_tests.ps1
```

Skripta automatski pokušava koristiti:

1. `.venv\\Scripts\\python.exe`
2. `py -3`
3. `python`

Možeš proslijediti i dodatne argumente, npr.:

```powershell
.\run_intent_tests.ps1 --log-level DEBUG
```

## Dialog validation na Windows PowerShell

Iz root direktorija projekta pokreni:

```powershell
.\run_dialog_validation.ps1
```

Dodatni argumenti također rade, npr.:

```powershell
.\run_dialog_validation.ps1 --log-level DEBUG
```

Ako je PowerShell execution policy blokiran, u istoj sesiji pokreni:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```
