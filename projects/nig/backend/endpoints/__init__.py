import os
from typing import Any, List, Optional

from restapi.exceptions import NotFound
from restapi.rest.definition import EndpointResource
from restapi.services.authentication import User
from restapi.utilities.logs import log

GROUP_DIR = "/data/input"
OUTPUT_ROOT = "/data/output"

STUDY_NOT_FOUND = "This study cannot be found or you are not authorized to access"
DATASET_NOT_FOUND = "This dataset cannot be found or you are not authorized to access"
PHENOTYPE_NOT_FOUND = (
    "This phenotype cannot be found or you are not authorized to access"
)
TECHMETA_NOT_FOUND = (
    "This set of technical metadata cannot be found or you are not authorized to access"
)
FILE_NOT_FOUND = "This file cannot be found or you are not authorized to access"
# RESOURCE_NOT_FOUND = "This resource cannot be found or you are not authorized to access"

# Should be the class models, but can't be imported here
Study = Any
Dataset = Any
File = Any


class NIGEndpoint(EndpointResource):
    # group used for test or, in general, groups we don't want to be counted in stats
    GROUPS_TO_FILTER: List[str] = []

    def getPath(
        self,
        user: User,
        study: Optional[Study] = None,
        dataset: Optional[Dataset] = None,
        file: Optional[File] = None,
        read: bool = False,
    ) -> str:

        group = user.belongs_to.single()
        if not group:
            raise NotFound("User group not found")
        if study:
            path = os.path.join(GROUP_DIR, group.uuid, study.uuid)
        if dataset:
            study = dataset.parent_study.single()
            if read:
                # it can be an admin so i have to get the group uuid of the dataset
                owner = dataset.ownership.single()
                group = owner.belongs_to.single()
            path = os.path.join(GROUP_DIR, group.uuid, study.uuid, dataset.uuid)
        if file:
            dataset = file.dataset.single()
            study = dataset.parent_study.single()
            if read:
                # it can be an admin so i have to get the group uuid of the dataset
                owner = dataset.ownership.single()
                group = owner.belongs_to.single()
            path = os.path.join(
                GROUP_DIR, group.uuid, study.uuid, dataset.uuid, file.name
            )
        return path

    @staticmethod
    def getError(error_type: str) -> str:
        if error_type == "Study":
            return STUDY_NOT_FOUND
        if error_type == "Dataset":
            return DATASET_NOT_FOUND
        if error_type == "File":
            return FILE_NOT_FOUND
        # if error_type == "Resource":
        #     return RESOURCE_NOT_FOUND
        if error_type == "Phenotype":
            return PHENOTYPE_NOT_FOUND
        if error_type == "Technical Metadata":
            return TECHMETA_NOT_FOUND
        return "Resource not found"  # pragma: no cover

    # returns 2 values:
    #   - user has access True/False
    #   - a human readable motivation
    def verifyStudyAccess(
        self,
        study: Study,
        user: User,
        error_type: str = "Study",
        read: bool = False,
        raiseError: bool = True,
    ) -> bool:

        not_found = self.getError(error_type)

        if study is None:
            if raiseError:
                raise NotFound(not_found)
            else:
                return False

        owner = study.ownership.single()

        if owner is None:  # pragma: no cover
            log.warning("Study with null owner: %s" % study.uuid)
            return False

        # The owner has always access
        if owner == user:
            return True

        # An admin has always access for readonly
        if read and self.auth.is_admin(user):
            return True

        # A member of the some group of the owner, has always access
        for group in owner.belongs_to.all():
            if group.members.is_connected(user):
                return True

        if raiseError:
            raise NotFound(not_found)
        else:
            return False

    def verifyDatasetAccess(
        self,
        dataset: Dataset,
        user: User,
        error_type: str = "Dataset",
        read: bool = False,
        raiseError: bool = True,
    ) -> bool:

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

        # The owner has always access
        if owner == user:
            return True

        # An admin has always access for readonly
        if read and self.auth.is_admin(user):
            return True

        # A member of the some group of the owner, has always access
        for group in owner.belongs_to.all():
            if group.members.is_connected(user):
                return True

        if raiseError:
            raise NotFound(not_found)
        else:
            return False
