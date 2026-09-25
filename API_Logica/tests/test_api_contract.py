import re
import unittest
from unittest.mock import patch

import httpx

from server.server import app
from testlogica.prolog.codec import collect_variables, from_prolog

TRANSLATION_PAYLOAD = {
    "mode": "propositional",
    "quantifier_ratio": 0,
    "wrong_options_count": 3,
    "names_pool": ["Anna", "Bruno", "Carla"],
    "people_count": 3,
    "actions_pool": ["studia", "corre", "legge"],
    "allow_spoken_mode": False,
    "seed": 7,
}


class ApiContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        transport = httpx.ASGITransport(app=app)
        self.client = httpx.AsyncClient(transport=transport, base_url="http://testserver")

    async def asyncTearDown(self) -> None:
        await self.client.aclose()

    async def test_translation_accepts_canonical_timeout(self) -> None:
        response = await self.client.post(
            "/api/generator/build-translation-question",
            json={**TRANSLATION_PAYLOAD, "timeout": 5},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"]["type"], "translation_question")

    async def test_translation_keeps_legacy_timeout_alias(self) -> None:
        response = await self.client.post(
            "/api/generator/build-translation-question",
            json={**TRANSLATION_PAYLOAD, "timeout_seconds": 5},
        )

        self.assertEqual(response.status_code, 200)

    async def test_formula_injection_is_rejected_before_prolog_execution(self) -> None:
        response = await self.client.post(
            "/api/prolog-bridge/logic/eval",
            json={"expr": "p),halt,(", "valuation": [{"name": "p", "value": True}]},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "INVALID_INPUT")

    async def test_request_ids_are_preserved_or_replaced_safely(self) -> None:
        preserved = await self.client.get("/health", headers={"X-Request-ID": "client-42"})
        replaced = await self.client.get("/health", headers={"X-Request-ID": "invalid id"})

        self.assertEqual(preserved.headers["X-Request-ID"], "client-42")
        self.assertRegex(replaced.headers["X-Request-ID"], re.compile(r"^[0-9a-f]{32}$"))

    async def test_openapi_operation_ids_are_unique(self) -> None:
        document = (await self.client.get("/openapi.json")).json()
        operation_ids = [
            operation["operationId"]
            for path in document["paths"].values()
            for operation in path.values()
            if isinstance(operation, dict) and "operationId" in operation
        ]

        self.assertEqual(len(operation_ids), len(set(operation_ids)))

    async def test_openapi_documents_cross_field_and_nested_batch_constraints(self) -> None:
        document = (await self.client.get("/openapi.json")).json()
        schemas = document["components"]["schemas"]

        consequence = schemas["LogicalConsequenceQuestionRequest"]
        self.assertEqual(
            consequence["x-option-count-constraints"],
            {"sum_multiple_of": 2, "sum_maximum": 8},
        )
        self.assertIn("totale", consequence["description"])

        translation = schemas["TranslationQuestionRequest"]
        self.assertEqual(
            translation["x-pool-capacity-constraints"],
            {
                "quantifier_distinct_actions_minimum": "people_count oppure 2",
                "propositional_distinct_descriptions_minimum": 2,
                "propositional_chain_distinct_descriptions_minimum": 3,
            },
        )
        self.assertIn("atomi distinti", translation["description"])

        batch_item = schemas["MultipleQuestionItemRequest"]
        self.assertIn("stesso modello", batch_item["properties"]["payload"]["description"])

    async def test_translation_rejects_synonymous_atom_pools(self) -> None:
        response = await self.client.post(
            "/api/generator/build-translation-question",
            json={
                **TRANSLATION_PAYLOAD,
                "people_count": 1,
                "names_pool": ["Anna", "Anna"],
                "actions_pool": ["corre", "corre"],
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "REQUEST_VALIDATION_ERROR")

    async def test_capabilities_expose_quiz_limits_without_prolog(self) -> None:
        with patch("server.routes.MAX_BATCH_SIZE", 50):
            response = await self.client.get("/api/capabilities")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["version"], 1)
        self.assertIn("equivalence", payload["question_types"])
        self.assertEqual(payload["limits"]["question_count"], {"minimum": 1, "maximum": 100})
        self.assertEqual(payload["limits"]["batch_size"], 50)
        self.assertGreater(
            payload["limits"]["question_count"]["maximum"],
            payload["limits"]["batch_size"],
        )
        self.assertEqual(payload["limits"]["formula_variable_count"]["maximum"], 5)
        self.assertEqual(
            payload["limits"]["equivalence_wrong_option_count"],
            {"minimum": 1, "maximum": 21, "explicit_formula_maximum": 3},
        )
        self.assertEqual(payload["limits"]["logical_consequence_variable_count"], {"minimum": 2, "maximum": 5})
        self.assertEqual(payload["limits"]["logical_consequence_option_count"]["maximum"], 8)
        self.assertEqual(payload["limits"]["translation_wrong_option_count"], 3)
        self.assertTrue(payload["features"]["transformation_trace"])

    async def test_explicit_equivalence_uses_its_reliable_distractor_limit(self) -> None:
        response = await self.client.post(
            "/api/generator/build-exercise",
            json={"expr": "and(p,q)", "wrong_answers_count": 4, "seed": 42},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "REQUEST_VALIDATION_ERROR")

    async def test_readiness_probes_the_persistent_prolog_session(self) -> None:
        response = await self.client.get("/ready")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"status": "ready"})

    async def test_documented_build_exercise_payload_has_a_complete_transformation(self) -> None:
        response = await self.client.post(
            "/api/generator/build-exercise",
            json={"expr": "imp(p,q)", "wrong_answers_count": 3, "seed": 42},
        )

        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["result"]
        transformation = result["modified_formula"]["transformation"]
        self.assertEqual(transformation["source_formula_prolog"], "imp(p,q)")
        self.assertEqual(transformation["final_formula_prolog"], result["correct_answer_prolog"])
        self.assertGreaterEqual(len(transformation["steps"]), 2)

    async def test_formula_generation_with_four_and_five_variables_does_not_return_422(self) -> None:
        for variable_count in (4, 5):
            with self.subTest(variable_count=variable_count):
                response = await self.client.post(
                    "/api/generator/generate-formula-by-variable-count",
                    json={"variable_count": variable_count, "seed": 41, "timeout": 10},
                )

                self.assertEqual(response.status_code, 200, response.text)
                formula = from_prolog(response.json()["result"])
                self.assertEqual(len(collect_variables(formula)), variable_count)


if __name__ == "__main__":
    unittest.main()
