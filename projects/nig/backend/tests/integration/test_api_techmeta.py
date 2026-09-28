from faker import Faker
from nig.tests import test_env
from restapi.tests import API_URI, BaseTests, FlaskClient


class TestApp(BaseTests):
    def test_api_techmeta(
        self,
        client: FlaskClient,
        faker: Faker,
        test_env,
    ) -> None:
        # setup the test env
        (
            admin_headers,
            uuid_group_A,
            user_A1_uuid,
            user_A1_headers,
            uuid_group_B,
            user_B1_uuid,
            user_B1_headers,
            user_B2_uuid,
            user_B2_headers,
            study1_uuid,
            study2_uuid,
        ) = test_env.setup(study=True)

        # create a new techmeta
        techmeta1 = {
            "name": faker.pystr(),
            "sequencing_date": faker.date(),
            "platform": "Illumina",
            "enrichment_kit": "Twist_Human_Comprehensive_Exome",
        }
        r = client.post(
            f"{API_URI}/study/{study1_uuid}/technicals",
            headers=user_B1_headers,
            json=techmeta1,
        )
        assert r.status_code == 200
        techmeta1_uuid = self.get_content(r)
        assert isinstance(techmeta1_uuid, str)

        # create a new techmeta in a study of an other group
        r = client.post(
            f"{API_URI}/study/{study2_uuid}/technicals",
            headers=user_B1_headers,
            json=techmeta1,
        )
        assert r.status_code == 404

        # create a new technical as admin not belonging to study group
        techmeta2 = {
            "name": faker.pystr(),
            "sequencing_date": faker.date(),
            "platform": "Illumina",
            "enrichment_kit": "Twist_Human_Comprehensive_Exome",
        }
        r = client.post(
            f"{API_URI}/study/{study1_uuid}/technicals",
            headers=admin_headers,
            json=techmeta2,
        )
        assert r.status_code == 404

        r = client.post(
            f"{API_URI}/study/{study1_uuid}/technicals",
            headers=user_B1_headers,
            json=techmeta2,
        )
        assert r.status_code == 200
        techmeta2_uuid = self.get_content(r)
        assert isinstance(techmeta2_uuid, str)

        # test technical access
        # test technical list response
        r = client.get(
            f"{API_URI}/study/{study1_uuid}/technicals", headers=user_B1_headers
        )
        assert r.status_code == 200
        response = self.get_content(r)
        assert isinstance(response, list)
        assert len(response) == 2

        # test technical list response for a study you don't have access
        r = client.get(
            f"{API_URI}/study/{study2_uuid}/technicals", headers=user_B1_headers
        )
        assert r.status_code == 404

        # test technical list response for admin
        r = client.get(
            f"{API_URI}/study/{study1_uuid}/technicals", headers=admin_headers
        )
        assert r.status_code == 200
        response = self.get_content(r)
        assert isinstance(response, list)
        assert len(response) == 2

        # test empty list of technicals in a study
        r = client.get(
            f"{API_URI}/study/{study2_uuid}/technicals", headers=user_A1_headers
        )
        assert r.status_code == 200
        response = self.get_content(r)
        assert isinstance(response, list)
        assert not response

        # study owner
        r = client.get(f"{API_URI}/technical/{techmeta1_uuid}", headers=user_B1_headers)
        assert r.status_code == 200
        # same group of the study owner
        r = client.get(f"{API_URI}/technical/{techmeta1_uuid}", headers=user_B2_headers)
        assert r.status_code == 200
        # technical owned by an other group
        r = client.get(f"{API_URI}/technical/{techmeta1_uuid}", headers=user_A1_headers)
        assert r.status_code == 404
        not_authorized_message = self.get_content(r)
        assert isinstance(not_authorized_message, str)

        # admin access
        r = client.get(f"{API_URI}/technical/{techmeta1_uuid}", headers=admin_headers)
        assert r.status_code == 200

        # test technical modification

        # modify a non existent technical
        random_technical = faker.pystr()
        r = client.put(
            f"{API_URI}/technical/{random_technical}",
            headers=user_A1_headers,
            json={"name": faker.pystr()},
        )
        assert r.status_code == 404
        # modify a technical you do not own
        r = client.put(
            f"{API_URI}/technical/{techmeta1_uuid}",
            headers=user_A1_headers,
            json={"name": faker.pystr()},
        )
        assert r.status_code == 404
        # modify a technical you own
        r = client.put(
            f"{API_URI}/technical/{techmeta1_uuid}",
            headers=user_B1_headers,
            json={"name": faker.pystr(), "sequencing_date": faker.date()},
        )
        assert r.status_code == 204

        # admin modify a technical of a group he don't belongs
        r = client.put(
            f"{API_URI}/technical/{techmeta1_uuid}",
            headers=admin_headers,
            json={"name": faker.pystr()},
        )
        assert r.status_code == 404

        # delete a technical
        # delete a technical that does not exists
        r = client.delete(
            f"{API_URI}/technical/{random_technical}", headers=user_A1_headers
        )
        assert r.status_code == 404
        # delete a technical in a study you do not own
        r = client.delete(
            f"{API_URI}/technical/{techmeta1_uuid}", headers=user_A1_headers
        )
        assert r.status_code == 404
        # admin delete a technical of a group he don't belong
        r = client.delete(
            f"{API_URI}/technical/{techmeta1_uuid}", headers=admin_headers
        )
        assert r.status_code == 404
        # delete a technical in a study you own
        r = client.delete(
            f"{API_URI}/technical/{techmeta1_uuid}", headers=user_B1_headers
        )
        assert r.status_code == 204
        # delete a technical in a study own by your group
        r = client.delete(
            f"{API_URI}/technical/{techmeta2_uuid}", headers=user_B2_headers
        )
        assert r.status_code == 204
        # check technical deletion
        r = client.get(f"{API_URI}/technical/{techmeta1_uuid}", headers=user_B1_headers)
        assert r.status_code == 404
        not_existent_message = self.get_content(r)
        assert isinstance(not_existent_message, str)
        assert not_existent_message == not_authorized_message

        # --- issue #61: enrichment_kit is optional/absent for genome studies ---
        genome_study_uuid = test_env.create_study(user_B1_headers, study_type="genome")

        # POST without enrichment_kit succeeds for a genome study
        genome_techmeta = {"name": faker.pystr(), "platform": "Illumina"}
        r = client.post(
            f"{API_URI}/study/{genome_study_uuid}/technicals",
            headers=user_B1_headers,
            json=genome_techmeta,
        )
        assert r.status_code == 200
        genome_techmeta_uuid = self.get_content(r)
        assert isinstance(genome_techmeta_uuid, str)

        # POST with enrichment_kit is rejected for a genome study (unknown field)
        r = client.post(
            f"{API_URI}/study/{genome_study_uuid}/technicals",
            headers=user_B1_headers,
            json={
                **genome_techmeta,
                "enrichment_kit": "Twist_Human_Comprehensive_Exome",
            },
        )
        assert r.status_code == 400

        # POST without enrichment_kit is rejected for an exome study
        r = client.post(
            f"{API_URI}/study/{study1_uuid}/technicals",
            headers=user_B1_headers,
            json={"name": faker.pystr(), "platform": "Illumina"},
        )
        assert r.status_code == 400

        # get_schema reflects the parent study type: no enrichment_kit for genome
        r = client.post(
            f"{API_URI}/study/{genome_study_uuid}/technicals",
            headers=user_B1_headers,
            json={"get_schema": True},
        )
        assert r.status_code == 200
        genome_schema = self.get_content(r)
        assert isinstance(genome_schema, list)
        assert not any(f["key"] == "enrichment_kit" for f in genome_schema)

        # ... and present, required, with options for an exome study
        r = client.post(
            f"{API_URI}/study/{study1_uuid}/technicals",
            headers=user_B1_headers,
            json={"get_schema": True},
        )
        assert r.status_code == 200
        exome_schema = self.get_content(r)
        assert isinstance(exome_schema, list)
        kit_field = next(f for f in exome_schema if f["key"] == "enrichment_kit")
        assert kit_field["required"] is True
        assert kit_field["options"] == {
            "Agilent_SureSelect_Clinical_Research_Exome_v1": "Agilent_SureSelect_Clinical_Research_Exome_v1",
            "Agilent_SureSelect_AllExon_V8": "Agilent_SureSelect_AllExon_V8",
            "Agilent_SureSelectXT_AllExon_V6": "Agilent_SureSelectXT_AllExon_V6",
            "Illumina_Prep_Exome_V2.0_Plus": "Illumina_Prep_Exome_V2.0_Plus",
            "Illumina_Twist_Bioscience_V2.0": "Illumina_Twist_Bioscience_V2.0",
            "Illumina_TruSeq_Exome_V1.2": "Illumina_TruSeq_Exome_V1.2",
            "Illumina_TruSeq_Rapid_Exome": "Illumina_TruSeq_Rapid_Exome",
            "Twist_Human_Comprehensive_Exome": "Twist_Human_Comprehensive_Exome",
            "Roche_SeqCap_EZ_Exome_V3": "Roche_SeqCap_EZ_Exome_V3",
            "KAPA_HyperExome_hg38_primary_targets_v2_slop50": "KAPA_HyperExome_hg38_primary_targets_v2_slop50",
        }
        platform_field = next(f for f in exome_schema if f["key"] == "platform")
        assert platform_field["options"] == {
            "Illumina": "Illumina (NovaSeq, NextSeq, HiSeq, MiSeq)"
        }

        # PUT get_schema on a genome technical also omits enrichment_kit
        r = client.put(
            f"{API_URI}/technical/{genome_techmeta_uuid}",
            headers=user_B1_headers,
            json={"get_schema": True},
        )
        assert r.status_code == 200
        genome_put_schema = self.get_content(r)
        assert isinstance(genome_put_schema, list)
        assert not any(f["key"] == "enrichment_kit" for f in genome_put_schema)

        # the empty-string -> None platform normalization still works on the
        # dynamically generated schema
        r = client.put(
            f"{API_URI}/technical/{genome_techmeta_uuid}",
            headers=user_B1_headers,
            json={"platform": ""},
        )
        assert r.status_code == 204
        r = client.get(
            f"{API_URI}/technical/{genome_techmeta_uuid}", headers=user_B1_headers
        )
        assert r.status_code == 200
        assert self.get_content(r)["platform"] is None

        # cleanup: deleting the genome study also cascades its technical
        r = client.delete(
            f"{API_URI}/study/{genome_study_uuid}", headers=user_B1_headers
        )
        assert r.status_code == 204

        # --- issue #49: platform and enrichment kit are independent choices ---
        # Platforms currently expose only Illumina; an unsupported platform is
        # rejected without introducing a platform-to-kit compatibility mapping.
        r = client.post(
            f"{API_URI}/study/{study1_uuid}/technicals",
            headers=user_B1_headers,
            json={
                "name": faker.pystr(),
                "platform": "Ion",
                "enrichment_kit": "Twist_Human_Comprehensive_Exome",
            },
        )
        assert r.status_code == 400

        # The agreed enrichment kits are accepted independently of further
        # platform/kit association rules.
        r = client.post(
            f"{API_URI}/study/{study1_uuid}/technicals",
            headers=user_B1_headers,
            json={
                "name": faker.pystr(),
                "platform": "Illumina",
                "enrichment_kit": "KAPA_HyperExome_hg38_primary_targets_v2_slop50",
            },
        )
        assert r.status_code == 200
        techmeta49_uuid = self.get_content(r)
        assert isinstance(techmeta49_uuid, str)

        # A legacy kit value is no longer accepted.
        r = client.put(
            f"{API_URI}/technical/{techmeta49_uuid}",
            headers=user_B1_headers,
            json={"enrichment_kit": "Twist Human Core Exome"},
        )
        assert r.status_code == 400

        # Updating only the kit remains valid for a listed choice.
        r = client.put(
            f"{API_URI}/technical/{techmeta49_uuid}",
            headers=user_B1_headers,
            json={"enrichment_kit": "Illumina_TruSeq_Exome_V1.2"},
        )
        assert r.status_code == 204

        # cleanup
        r = client.delete(
            f"{API_URI}/technical/{techmeta49_uuid}", headers=user_B1_headers
        )
        assert r.status_code == 204
