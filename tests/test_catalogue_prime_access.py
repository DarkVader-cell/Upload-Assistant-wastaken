# ruff: noqa: S101
"""Account-entitlement fixtures; public listing flags cannot qualify a title."""

from copy import deepcopy

import pytest

from src.catalogue_prime_access import classify

ITEM = "amzn1.dv.gti.66e03765-50f3-4b7e-89ed-c31e9aea7ee0"


def resource():
    return {
        "imdbTconst": "tt9777666",
        "gti": ITEM,
        "applyPrime": True,
        "actions": [
            {
                "metadata": {
                    "metadataActionType": "Playback",
                    "videoMaterialType": "Feature",
                    "userEntitlementMetadata": {"entitlementType": "PRIME_SUBSCRIPTION", "benefitType": None},
                    "playbackExperienceMetadata": {"playbackEnvelope": True},
                }
            }
        ],
    }


def decision(data, **overrides):
    return classify(data, **{"imdb": "tt9777666", "item": ITEM, "country": "GB", "expected_country": "GB", **overrides})


def test_native_subscription_feature_uses_exact_enclosing_resource_when_title_omitted():
    result = decision(resource())
    assert result["state"] == "included" and result["method"] == "native_prime_subscription_v1"
    assert "actions" not in result and "envelope" not in str(result)


@pytest.mark.parametrize("kind", ["FREE", "RENTAL", "PURCHASE", "OWNED", "CHANNEL_SUBSCRIPTION", "TVOD", "UNKNOWN", "PRIME_SUBSCRIPTION_WITH_ADS"])
def test_non_subscription_or_unrecognized_entitlements_never_qualify(kind):
    data = resource()
    data["actions"][0]["metadata"]["userEntitlementMetadata"]["entitlementType"] = kind
    assert decision(data)["state"] != "included"


@pytest.mark.parametrize(
    "change",
    [
        {"videoMaterialType": "Trailer"},
        {"isTrailer": True},
        {"isUnopenedRental": True},
        {"playbackExperienceMetadata": {}},
        {"playbackTitle": "another-title"},
        {"userEntitlementMetadata": {"entitlementType": "PRIME_SUBSCRIPTION", "benefitType": "EXTRA_CHANNEL"}},
        {"metadataActionType": "Purchase"},
    ],
)
def test_paid_trailers_unknown_benefits_and_cross_title_playback_do_not_qualify(change):
    data = resource()
    data["actions"][0]["metadata"].update(deepcopy(change))
    assert decision(data)["state"] != "included"


def test_public_prime_flag_and_envelope_alone_are_not_entitlement():
    data = resource()
    data["actions"][0]["metadata"].pop("userEntitlementMetadata")
    assert decision(data)["state"] == "unknown"


def test_native_identity_and_profile_country_must_match():
    data = resource()
    assert decision(data, imdb="tt1234567")["state"] == "unknown"
    assert decision(data, expected_country="US")["state"] == "unknown"
    assert decision(data, item="unverified-alias")["state"] == "unknown"


def test_nested_full_subscription_and_free_trailer_are_distinct():
    data = resource()
    feature = data["actions"][0]
    data["actions"] = [
        {
            "childActions": [
                feature,
                {
                    "metadata": {
                        "metadataActionType": "Playback",
                        "videoMaterialType": "Trailer",
                        "userEntitlementMetadata": {"entitlementType": "FREE"},
                        "playbackExperienceMetadata": {"playbackEnvelope": True},
                    }
                },
            ]
        }
    ]
    assert decision(data)["state"] == "included"
