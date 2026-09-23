from restapi.connectors.celery import CeleryExt, CeleryRetryTask, Ignore, Task
from restapi.utilities.logs import log
from restapi.connectors import neo4j


class MyException(Exception):
    pass


@CeleryExt.task(idempotent=True, autoretry_for=(MyException,))
def test_task(self: Task[[str], str], myinput: str) -> str:
    log.info("Task ID: {}", self.request.id)

    db = neo4j.get_instance()

    if myinput == "wrong":
        raise AttributeError(
            "You can raise exceptions to stop the task execution in case of errors"
        )

    if myinput == "ignore":
        raise Ignore(
            "You can raise exceptions to stop the execution but without sending emails"
        )

    if myinput == "retry":
        raise CeleryRetryTask(
            "Force the retry of this task"
        )

    if myinput == "retry2":
        raise MyException(
            "Force the retry of this task by using a custom exception"
        )

    log.info("Task executed!")

    return "Task executed!"

# Note to execute this task from an endpoint:
#
# celery_ext = celery.get_instance()
# task = celery_ext.celery_app.send_task(
#     "test_task",
#     args=(...,)
# )
# log.debug("Task id={}", task.id)
