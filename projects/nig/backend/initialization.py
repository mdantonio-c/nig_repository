import csv
from typing import List, Optional

from restapi.config import DATA_PATH, PRODUCTION
from restapi.connectors import Connector, neo4j
from restapi.env import Env
from restapi.utilities.logs import log

from nig.services.admin_policy import RootIntegrityError, assert_root_integrity


class Initializer:
    def __init__(self) -> None:
        # enter GeoData in neo4j
        attributes: Optional[List[str]] = None
        graph = neo4j.get_instance()
        with open(DATA_PATH.joinpath("resources_for_db_setup", "geodata.tsv")) as fd:
            rd = csv.reader(fd, delimiter="\t", quotechar='"')
            for row in rd:
                if not attributes:
                    # use the first row to get the list of attributes
                    attributes = row
                else:
                    props = dict(zip(attributes, row))
                    geodata = graph.GeoData.nodes.get_or_none(**{attributes[0]: row[0]})
                    if not geodata:
                        # create a new one
                        geodata = graph.GeoData(**props).save()
                    else:
                        # check if an update is needed
                        for key, value in props.items():
                            if getattr(geodata, key) != value:
                                setattr(geodata, key, value)
                                geodata.save()

        log.info("GeoData nodes succesfully created")

        auth = Connector.get_authentication_instance()
        try:
            report = assert_root_integrity(auth)
            log.info("Root integrity verified for user {}", report.root_uuid)
        except RootIntegrityError as exc:
            if PRODUCTION or Env.get_bool("AUTH_ADMIN_HIERARCHY_ENFORCE"):
                log.critical("Root integrity check failed: {}", exc)
                raise
            log.warning(
                "Root integrity check failed in non-enforcing mode: {}. "
                "Run the admin hierarchy migration before enabling enforcement.",
                exc,
            )

    # This method is called after normal initialization if TESTING mode is enabled
    def initialize_testing_environment(self) -> None:
        pass
