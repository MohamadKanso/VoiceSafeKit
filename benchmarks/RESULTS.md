SpokenPII v1: 580 sentences (270 written PII, 270 spoken PII, 40 tricky no-PII).

| Detector | Written PII protected | Spoken PII protected | False alarms on no-PII | Median latency |
|---|---:|---:|---:|---:|
| VoiceSafeKit 0.5 | 100% | 100% | 0% | 0.06 ms |
| VoiceSafeKit 0.5 (spoken mode off) | 100% | 11% | 0% | 0.04 ms |
| Microsoft Presidio | 86% | 21% | 45% | 3.51 ms |

Spoken PII protected, by type:

| Type | VoiceSafeKit 0.5 | VoiceSafeKit 0.5 (spoken mode off) | Microsoft Presidio |
|---|---:|---:|---:|
| card | 100% | 0% | 0% |
| dob | 100% | 0% | 77% |
| email | 100% | 0% | 0% |
| name | 100% | 100% | 97% |
| otp | 100% | 0% | 3% |
| passport | 100% | 0% | 0% |
| phone | 100% | 0% | 0% |
| pin | 100% | 0% | 13% |
| ssn | 100% | 0% | 3% |
