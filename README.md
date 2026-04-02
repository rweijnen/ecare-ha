# eCare Dossier Monitor

> ⚠️ **STATUS: EXPERIMENTEEL / WORK IN PROGRESS**
>
> Deze integratie is in actieve ontwikkeling en nog niet productie-gereed.
> Gebruik op eigen risico. API-koppeling is gebaseerd op reverse engineering
> van het Puur van Jou portaal en kan zonder aankondiging breken.

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
![Maintenance](https://img.shields.io/badge/Maintained%3F-yes-green.svg)
![Status](https://img.shields.io/badge/Status-Experimenteel-orange)

Home Assistant integratie die het eCare zorgdossier (Puur van Jou / wijkzorg) monitort
en een melding stuurt via Telegram (of andere HA notificaties) wanneer er een nieuw item
verschijnt in het dagboek.

## Achtergrond

[eCare.nl](https://ecare.nl) is een zorgdossier platform dat gebruikt wordt door Nederlandse
wijkzorgorganisaties. Via [wijkzorg.puurvanjou.nl](https://wijkzorg.puurvanjou.nl) kunnen
familieleden het dossier inzien. Deze integratie pollt de achterliggende API en vuurt een
Home Assistant event zodra er een nieuw dagboek-item verschijnt.

## Installatie via HACS

1. Ga naar HACS → Integraties → ⋮ → **Aangepaste opslagplaatsen**
2. Voeg toe: `https://github.com/rweijnen/ecare-ha` als type **Integratie**
3. Zoek op "eCare" en installeer
4. Herstart Home Assistant

## Handmatige installatie

Kopieer de map `custom_components/ecare/` naar `<config>/custom_components/ecare/` en herstart HA.

## Configuratie

Ga naar **Instellingen → Integraties → + Toevoegen → eCare Dossier Monitor**

### Stap 1 — Inloggegevens
Voer je e-mailadres en wachtwoord in van je Puur van Jou account.

### Stap 2 — SMS verificatie
Je ontvangt een SMS van **+31 970 10 20 50 53**. Voer de code in.

Na de eerste keer inloggen wordt de sessie opgeslagen. Toekomstige token-vernieuwingen
verlopen automatisch **zonder SMS** zolang de IDP-sessie geldig is (typisch weken tot maanden).
Als de sessie verloopt, vraagt HA je opnieuw te configureren.

## Entities

| Entity | Beschrijving |
|--------|-------------|
| `sensor.ecare_dagboek_items` | Totaal aantal items in het dagboek |
| `sensor.ecare_laatste_gebeurtenis` | Omschrijving van het meest recente item |

## Events

Bij elk nieuw dagboek-item wordt het event `ecare_new_item` gevuurd:

| Attribuut | Voorbeeld |
|-----------|-----------|
| `id` | `14f2b911-b556-4d82-...` |
| `type` | `rapportage` of `zorgmoment` |
| `datum` | `02-04-2026` |
| `tijd` | `10:36` |
| `wie` | `Merel` |
| `discipline` | `Verpleging` |
| `onderwerp` | `Medicatie` |
| `tekst` | Inhoud (max 500 tekens, HTML gestript) |

## Telegram notificatie

Vereist: [Telegram bot integratie](https://www.home-assistant.io/integrations/telegram/) al geconfigureerd in HA.

Voeg toe aan `automations.yaml`:

```yaml
alias: eCare - Stuur Telegram bij nieuw dagboek-item
trigger:
  - platform: event
    event_type: ecare_new_item
action:
  - service: telegram_bot.send_message
    data:
      message: >
        📋 Nieuw in dossier:

        📅 {{ trigger.event.data.datum }} {{ trigger.event.data.tijd }}
        👤 {{ trigger.event.data.wie }} ({{ trigger.event.data.discipline }})
        🏷️ {{ trigger.event.data.type }}
        {% if trigger.event.data.onderwerp %}📌 {{ trigger.event.data.onderwerp }}
        {% endif %}
        {{ trigger.event.data.tekst[:400] }}
```

## Poll interval aanpassen

Ga naar **Instellingen → Integraties → eCare → Configureren** (standaard: 15 minuten, min: 5, max: 60).

## Bekende beperkingen

- Werkt alleen voor het **Puur van Jou** portaal (`wijkzorg.puurvanjou.nl`)
- Andere eCare-portalen (bijv. woonzorg) zijn nog niet getest
- De API is niet officieel gedocumenteerd en kan wijzigen
- Sessie verloopt na verloop van tijd → opnieuw configureren met SMS vereist

## Technische details

De integratie gebruikt de [IdentityServer4](https://identityserver4.readthedocs.io/) OIDC
implicit flow van `pvj-idp.ecare.nl`. Na de initiële SMS-verificatie worden de sessiecookies
opgeslagen en wordt `prompt=none` gebruikt voor stille token-vernieuwing.

## Bijdragen

Issues en pull requests zijn welkom. Dit project is gestart als persoonlijk hulpmiddel
en wordt gedeeld in de hoop dat het anderen ook van pas komt.

## Disclaimer

Deze integratie is niet gelieerd aan of goedgekeurd door eCare.nl of Puur van Jou.
Gebruik is voor eigen risico.
