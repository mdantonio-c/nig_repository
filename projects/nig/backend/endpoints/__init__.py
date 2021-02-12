import os

from restapi.exceptions import NotFound
from restapi.rest.definition import EndpointResource
from restapi.utilities.logs import log

GROUP_DIR = "/data"

STUDY_NOT_FOUND = "This study cannot be found or you are not authorized to access"
DATASET_NOT_FOUND = "This dataset cannot be found or you are not authorized to access"
PHENOTYPE_NOT_FOUND = (
    "This phenotype cannot be found or you are not authorized to access"
)
TECHMETA_NOT_FOUND = (
    "This set of technical metadata cannot be found or you are not authorized to access"
)
FILE_NOT_FOUND = "This file cannot be found or you are not authorized to access"
RESOURCE_NOT_FOUND = "This resource cannot be found or you are not authorized to access"


class NIGEndpoint(EndpointResource):
    def getPath(self, study=None, dataset=None, file=None):
        current_user = self.get_user()
        group = current_user.belongs_to.single()
        if not group:
            raise NotFound("User group not found")
        if study:
            path = os.path.join(GROUP_DIR, group.uuid, study.uuid)
        if dataset:
            study = dataset.parent_study.single()
            path = os.path.join(GROUP_DIR, group.uuid, study.uuid, dataset.uuid)
        return path

    @staticmethod
    def getSingleLinkedNode(relation):

        log.warning(
            "Deprecated use of getSingleLinkedNode, use relation.single() instead"
        )
        return relation.single()

    @staticmethod
    def createUniqueIndex(*var):

        separator = "#_#"
        return separator.join(var)

    @staticmethod
    def getError(error_type: str) -> str:
        if error_type == "Study":
            return STUDY_NOT_FOUND
        if error_type == "Dataset":
            return DATASET_NOT_FOUND
        if error_type == "File":
            return FILE_NOT_FOUND
        if error_type == "Resource":
            return RESOURCE_NOT_FOUND
        if error_type == "Phenotype":
            return PHENOTYPE_NOT_FOUND
        if error_type == "Technical Metadata":
            return TECHMETA_NOT_FOUND
        return "Resource not found"

    # returns 2 values:
    #   - user has access True/False
    #   - a human readable motivation
    def verifyStudyAccess(self, study, error_type="Study", read=False, raiseError=True):

        not_found = self.getError(error_type)

        if study is None:
            if raiseError:
                raise NotFound(not_found)
            else:
                return False, "error, null study"

        owner = study.ownership.single()

        if owner is None:
            log.warning("Study with null owner: %s" % study.uuid)
            return False, "error, null owner"

        current_user = self.get_user()
        # The owner has always access
        if owner == current_user:
            return True, "you are the owner"

        # An admin has always access for readonly
        if read and self.verify_admin():
            return True, "you are an admin"

        # A member of the some group of the owner, has always access
        for group in owner.belongs_to.all():
            if group.members.is_connected(current_user):
                return True, "you share a group with the owner"

        if raiseError:
            raise NotFound(not_found)
        else:
            return False, "you have no access"

    def verifyDatasetAccess(
        self, dataset, error_type="Dataset", read=False, raiseError=True
    ):

        not_found = self.getError(error_type)

        if dataset is None:
            if raiseError:
                raise NotFound(not_found)
            else:
                return False

        # The owner has always access
        owner = dataset.ownership.single()

        if owner is None:
            log.warning("Dataset with null owner: %s" % dataset.uuid)
            return False

        current_user = self.get_user()

        # The owner has always access
        if owner == current_user:
            return True

        # An admin has always access
        if self.verify_admin():
            return True, "you are an admin", True

        # A member of the some group of the owner, has always access
        for group in owner.belongs_to.all():
            if group.members.is_connected(current_user):
                return True

        if raiseError:
            raise NotFound(not_found)
        else:
            return False
