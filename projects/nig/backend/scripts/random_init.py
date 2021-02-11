import random
from datetime import datetime

import pytz
from faker import Faker
from restapi.connectors import Connector, neo4j

auth = Connector.get_authentication_instance()
graph = neo4j.get_instance()
fake = Faker()

users = auth.get_users()

for i in range(0, 5):

    user = random.choice(users)

    s = graph.Study(name=fake.license_plate(), description=fake.text(40)).save()

    s.ownership.connect(user)

    for i in range(0, 4):
        d = graph.Dataset(name=fake.name(), description=fake.text(20)).save()

        d.ownership.connect(user)
        s.datasets.connect(d)

        p = graph.Phenotype(
            name=fake.license_plate(),
            description=fake.pystr(),
            birthday=datetime.fromtimestamp(fake.unix_time(), pytz.utc),
            sex=random.choice(("M", "F")),
            birth_place=fake.city(),
            unique_name=fake.pystr(),
        ).save()

        s.phenotypes.connect(p)
        d.phenotype.connect(p)
