import logging
from collections import defaultdict
from functools import reduce

from topobank.manager.utils import dict_from_base64
from topobank.analysis.models import WorkflowTemplate
from topobank.analysis.utils import merge_dicts
from topobank.analysis.controller import AnalysisController as CoreAnalysisController
from ..serializers import ResultSerializer

_log = logging.getLogger(__name__)


class AnalysisController(CoreAnalysisController):
    """Retrieve and toggle status of analyses"""

    def __init__(
        self,
        user,
        subjects=None,
        workflow=None,
        workflow_name=None,
        kwargs=None,
        with_children=True,
    ):
        """
        Construct a controller object that filters for specific user, subjects,
        functions, and function arguments. If a parameter is None, then it
        does not filter for this property (but returns all analyses).

        Parameters
        ----------
        user : topobank.manager.models.User
            Currently logged-in user.
        subjects : list of Tag, Topography or Surface, optional
            Subjects for which to filter analyses. (Default: None)
        workflow : Workflow, optional
            Workflow function object. (Default: None)
        workflow_name : str, optional
            Name of analysis function. (Default: None)
        with_children : bool, optional
            Also return analyses of children, i.e. of topographies that belong
            to a surface. (Default: True)
        """
        super().__init__(
            user,
            subjects=subjects,
            workflow=workflow,
            workflow_name=workflow_name,
            kwargs=kwargs,
            with_children=with_children,
        )

    @staticmethod
    def get_request_parameter(names, data, multiple=False):
        retdata = data.copy()

        def set_value_multiple(value, name):
            new_value = retdata.get(name, None)
            if value is None:
                if new_value is not None:
                    del retdata[name]
                    if isinstance(new_value, list):
                        return new_value
                    else:
                        return [new_value]
            elif new_value is not None:
                if isinstance(new_value, list):
                    return value + new_value
                else:
                    return value + [new_value]
            return value

        def set_value_single(value, name):
            new_value = retdata.get(name, None)
            if value is None:
                if new_value is not None:
                    if isinstance(new_value, list) and len(new_value) > 1:
                        errstr = reduce(lambda x, y: f"{x}, {y}", names)
                        raise ValueError(
                            f"Multiple values for query parameter '{errstr}'"
                        )
                    del retdata[name]
                    if isinstance(new_value, list):
                        (new_value,) = new_value
                return new_value
            elif new_value is not None:
                errstr = reduce(lambda x, y: f"{x}, {y}", names)
                raise ValueError(f"Multiple values for query parameter {errstr}")
            return value

        def set_value(value, name):
            if multiple:
                return set_value_multiple(value, name)
            else:
                return set_value_single(value, name)

        value = None
        for name in names:
            value = set_value(value, name)
        return value, retdata

    @staticmethod
    def from_request(request, with_children=True, **kwargs):
        """
        Construct an `AnalysisControlLer` object from a request object.

        Parameters
        ----------
        request : rest_framework.request.Request
            REST request object
        with_children : bool, optional
            Also return analyses of children, i.e. of topographies that belong
            to a surface. (Default: True)

        Returns
        -------
        controller : AnalysisController
            The analysis controller object
        """
        _queryable_subjects = ["tag", "surface", "topography"]

        user = request.user

        data = request.data | request.GET | kwargs
        workflow_name, data = AnalysisController.get_request_parameter(
            ["workflow"], data
        )

        subjects = defaultdict(list)
        subjects_str, data = AnalysisController.get_request_parameter(
            ["subjects"], data
        )
        if subjects_str is not None:
            subjects = defaultdict(list, dict_from_base64(subjects_str))

        for subject_key in _queryable_subjects:
            s, data = AnalysisController.get_request_parameter(
                [subject_key], data, multiple=True
            )
            if s is not None:
                try:
                    subjects[subject_key] += s
                except AttributeError:
                    raise ValueError(f"Malformed subject key '{subject_key}'")
                except ValueError:
                    raise ValueError(f"Malformed subject key '{subject_key}'")

        if len(subjects) == 0:
            subjects = None

        workflow_kwargs, data = AnalysisController.get_request_parameter(
            ["kwargs", "function_kwargs"], data
        )
        if workflow_kwargs is not None and isinstance(workflow_kwargs, str):
            workflow_kwargs = dict_from_base64(workflow_kwargs)

        workflow_template_id, data = AnalysisController.get_request_parameter(
            ["workflow_template"], data
        )
        if workflow_template_id is not None:
            workflow_template = WorkflowTemplate.objects.get(id=workflow_template_id)
            workflow_kwargs = merge_dicts(
                workflow_template.kwargs,
                [workflow_kwargs]
            )

        if len(data) > 0:
            raise ValueError(
                "Unknown query parameters: "
                f"{reduce(lambda x, y: f'{x}, {y}', data.keys())}"
            )

        return AnalysisController(
            user,
            subjects=subjects,
            workflow_name=workflow_name,
            kwargs=workflow_kwargs,
            with_children=with_children,
        )

    def to_representation(self, task_states=None, has_result_file=None, request=None):
        """
        Return list of serialized analyses filtered by arguments (if present).

        Parameters
        ----------
        task_states : list of str, optional
            List of task states to filter for, e.g. ['su', 'fa'] to filter for
            success and failure. (Default: None)
        has_result_file : boolean, optional
            If true, only return analyses that have a results file. If false,
            return analyses without a results file. Don't filter for results
            file if unset. (Default: None)
        request : Request, optional
            request object (for HyperlinkedRelatedField). (Default: None)
        """
        if request is None:
            context = None
        else:
            context = {"request": request}
        return [
            ResultSerializer(analysis, context=context).data
            for analysis in self.get(
                task_states=task_states, has_result_file=has_result_file
            )
        ]

    def get_context(self, task_states=None, has_result_file=None, request=None):
        """
        Construct a standardized context dictionary.

        Parameters
        ----------
        task_states : list of str, optional
            List of task states to filter for, e.g. ['su', 'fa'] to filter for
            success and failure. (Default: None)
        has_result_file : boolean, optional
            If true, only return analyses that have a results file. If false,
            return analyses without a results file. Don't filter for results
            file if unset. (Default: None)
        request : Request, optional
            request object (for HyperlinkedRelatedField). (Default: None)
        """
        return {
            "analyses": self.to_representation(
                task_states=task_states,
                has_result_file=has_result_file,
                request=request,
            ),
            "dois": self.dois,
            "workflow_name": self.workflow.name,
            "subjects": self.subjects_dict,  # can be used to re-trigger analyses
            "unique_kwargs": self.unique_kwargs,
            "has_nonunique_kwargs": self.has_nonunique_kwargs,
        }
