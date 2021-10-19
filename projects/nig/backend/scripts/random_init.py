import random
from datetime import datetime

import pytz
from faker import Faker
from nig.endpoints import GROUP_DIR
from restapi.connectors import Connector, neo4j

auth = Connector.get_authentication_instance()
graph = neo4j.get_instance()
faker = Faker()

users = auth.get_users()

for i in range(0, 5):

    user = random.choice(users)
    group = user.belongs_to.single()

    s = graph.Study(name=faker.license_plate(), description=faker.text(40)).save()

    study_path = GROUP_DIR.joinpath(group.uuid, s.uuid)
    study_path.mkdir(parents=True)
    s.ownership.connect(user)

    for i in range(0, 4):
        d = graph.Dataset(name=faker.name(), description=faker.text(20)).save()

        dataset_path = study_path.joinpath(d.uuid)
        dataset_path.mkdir(parents=True)

        d.ownership.connect(user)
        s.datasets.connect(d)

        p = graph.Phenotype(
            name=faker.license_plate(),
            description=faker.pystr(),
            birthday=datetime.fromtimestamp(faker.unix_time(), pytz.utc),
            sex=random.choice(("male", "female")),
            # birth_place=faker.city(),
            unique_name=faker.pystr(),
        ).save()

        s.phenotypes.connect(p)
        d.phenotype.connect(p)
