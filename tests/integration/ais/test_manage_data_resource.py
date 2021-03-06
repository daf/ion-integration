#!/usr/bin/env python

"""
@file inttest_ingest.py
@author Ian Katz <ijk5@mit.edu>
@test
"""

import ion.util.ionlog
from twisted.internet import defer

from ion.test.iontest import ItvTestCase
from ion.core import ioninit
from ion.core.exception import ReceivedApplicationError
from ion.util import procutils as pu
from ion.core.object import object_utils

from ion.integration.ais.app_integration_service import AppIntegrationServiceClient
from ion.integration.ais.manage_data_resource.manage_data_resource import DEFAULT_MAX_INGEST_MILLIS
from ion.services.coi.resource_registry.resource_client import ResourceClient
from ion.core.messaging.message_client import MessageClient
from ion.services.coi.resource_registry.association_client import AssociationClient
from ion.core.process.process import Process

from ion.services.coi.datastore_bootstrap.ion_preload_config import HAS_A_ID, \
                                                                    TYPE_OF_ID, \
                                                                    DATASET_RESOURCE_TYPE_ID, \
                                                                    DATASOURCE_RESOURCE_TYPE_ID, \
                                                                    DATARESOURCE_SCHEDULE_TYPE_ID

from ion.integration.ais.ais_object_identifiers import AIS_RESPONSE_MSG_TYPE, \
                                                       AIS_REQUEST_MSG_TYPE, \
                                                       AIS_RESPONSE_ERROR_TYPE, \
                                                       CREATE_DATA_RESOURCE_REQ_TYPE, \
                                                       CREATE_DATA_RESOURCE_RSP_TYPE, \
                                                       UPDATE_DATA_RESOURCE_REQ_TYPE, \
                                                       UPDATE_DATA_RESOURCE_RSP_TYPE, \
                                                       DELETE_DATA_RESOURCE_REQ_TYPE, \
                                                       DELETE_DATA_RESOURCE_RSP_TYPE, \
                                                       DATA_RESOURCE_SCHEDULED_TASK_TYPE


from ion.services.coi.datastore_bootstrap.ion_preload_config import SAMPLE_PROFILE_DATASET_ID, \
                                                                    SAMPLE_PROFILE_DATA_SOURCE_ID, \
                                                                    SAMPLE_STATION_DATA_SOURCE_ID

log = ion.util.ionlog.getLogger(__name__)
CONF = ioninit.config(__name__)

class IntTestAisManageDataResource(ItvTestCase):

    app_dependencies = [
                # release file for r1
                ("res/deploy/r1deploy.rel", "id=1"),
                ]

    @defer.inlineCallbacks
    def setUp(self):
        yield self._start_container()

        proc  = Process()
        yield proc.spawn()

        self.aisc  = AppIntegrationServiceClient(proc=proc)
        self.rc    = ResourceClient(proc=proc)
        self.mc    = MessageClient(proc=proc)
        self.ac    = AssociationClient(proc=proc)

    @defer.inlineCallbacks
    def tearDown(self):
        yield self._stop_container()


    @defer.inlineCallbacks
    def test_createDataResource(self):
        yield self._createDataResource()

    @defer.inlineCallbacks
    def test_createDeleteDataResource(self):
        #run the create
        create_resp = yield self._createDataResource()

        #try the delete
        yield self._deleteDataResource(create_resp.data_source_id)

    @defer.inlineCallbacks
    def test_createUpdateDeleteDataResource(self):
        #run the create
        log.info("FULL USAGE 1/3: create")
        create_resp = yield self._createDataResource()

        #run the update 
        log.info("FULL USAGE 2/3: update")
        yield self._updateDataResource(create_resp.data_source_id)

        #try the delete
        log.info("FULL USAGE 3/3: delete")
        yield self._deleteDataResource(create_resp.data_source_id)


    @defer.inlineCallbacks
    def test_updateDataResourceNull(self):
        """
        run through the update code but don't specify any ids.
        """

        log.info("Trying to call updateDataResource with the wrong GPB")
        update_req_msg  = yield self.mc.create_instance(UPDATE_DATA_RESOURCE_REQ_TYPE)
        result       = yield self.aisc.updateDataResource(update_req_msg)
        self.failUnlessEqual(result.MessageType, AIS_RESPONSE_ERROR_TYPE,
                             "updateDataResource accepted a GPB that was known to be the wrong type")


        log.info("Trying to call updateDataResource with an empty GPB")
        ais_req_msg  = yield self.mc.create_instance(AIS_REQUEST_MSG_TYPE)
        update_req_msg  = ais_req_msg.CreateObject(UPDATE_DATA_RESOURCE_REQ_TYPE)
        ais_req_msg.message_parameters_reference = update_req_msg
        result_wrapped = yield self.aisc.updateDataResource(ais_req_msg)
        self.failUnlessEqual(result_wrapped.MessageType, AIS_RESPONSE_ERROR_TYPE,
                             "updateDataResource accepted a GPB without a data_source_resource_id")


    @defer.inlineCallbacks
    def test_updateDataResourceSample(self):
        """
        try updating one of the preloaded data sources
        """

        log.info("Updating a sample data resource")
        yield self._updateDataResource(SAMPLE_PROFILE_DATA_SOURCE_ID)


    @defer.inlineCallbacks
    def _updateDataResource(self, data_source_resource_id):
        log.info("_updateDataResource(%s) " % data_source_resource_id)

        initial_resource = yield self.rc.get_instance(data_source_resource_id)
        log.info("Fetching the data resource manually to find out what's in it")

        #before 
        b4_max_ingest_millis            = initial_resource.max_ingest_millis
        b4_update_interval_seconds      = initial_resource.update_interval_seconds
        b4_update_start_datetime_millis = initial_resource.update_start_datetime_millis
        b4_ion_title                    = initial_resource.ion_title
        #b4_ion_institution_id           = initial_resource.ion_institution_id
        b4_ion_description              = initial_resource.ion_description
        log.info("Original values are %d, %d, %d, %s, %s" % (b4_max_ingest_millis,
                                                             b4_update_interval_seconds,
                                                             b4_update_start_datetime_millis,
                                                             #b4_ion_institution_id,
                                                             b4_ion_title,
                                                             b4_ion_description))

        log.info("Updating the resource based on what we found")
        fr_max_ingest_millis            = b4_max_ingest_millis + 1
        fr_update_interval_seconds      = b4_update_interval_seconds + 1
        fr_update_start_datetime_millis = b4_update_start_datetime_millis + 1
        #fr_ion_institution_id           = b4_ion_institution_id + "_updated"
        fr_ion_title                    = b4_ion_title + "_updated"
        fr_ion_description              = b4_ion_description + "_updated"


        log.info("new values will be %d, %d, %d, %s, %s" % (fr_max_ingest_millis,
                                                            fr_update_interval_seconds,
                                                            fr_update_start_datetime_millis,
                                                            #fr_ion_institution_id,
                                                            fr_ion_title,
                                                            fr_ion_description))

        log.info("Creating and wrapping update request message")
        ais_req_msg  = yield self.mc.create_instance(AIS_REQUEST_MSG_TYPE)
        update_req_msg  = ais_req_msg.CreateObject(UPDATE_DATA_RESOURCE_REQ_TYPE)
        ais_req_msg.message_parameters_reference = update_req_msg

        #what we want it to be
        update_req_msg.data_source_resource_id      = SAMPLE_PROFILE_DATA_SOURCE_ID
        update_req_msg.max_ingest_millis            = fr_max_ingest_millis
        update_req_msg.update_interval_seconds      = fr_update_interval_seconds
        update_req_msg.update_start_datetime_millis = fr_update_start_datetime_millis
        #update_req_msg.ion_institution_id           = fr_ion_institution_id
        update_req_msg.ion_title                    = fr_ion_title
        update_req_msg.ion_description              = fr_ion_description

        #actual update call
        result_wrapped = yield self.aisc.updateDataResource(ais_req_msg)

        log.info("Analyzing results of updateDataResource call")
        self.failUnlessEqual(result_wrapped.MessageType, AIS_RESPONSE_MSG_TYPE,
                             "updateDataResource had an internal failure")
        self.failUnlessEqual(200, result_wrapped.result, "deleteDataResource didn't return 200 OK")
        self.failUnlessEqual(1, len(result_wrapped.message_parameters_reference),
                             "updateDataResource returned a GPB with wrong number of 'message_parameters_reference's")

        #unpack result and dig deeper
        result = result_wrapped.message_parameters_reference[0]
        self.failUnlessEqual(result.success, True, "updateDataResource didn't report success")

        #look up resource to compare with fields from original
        updated_resource = yield self.rc.get_instance(SAMPLE_PROFILE_DATA_SOURCE_ID)
        self.failUnlessEqual(fr_max_ingest_millis             , updated_resource.max_ingest_millis)
        self.failUnlessEqual(fr_update_interval_seconds       , updated_resource.update_interval_seconds)
        self.failUnlessEqual(fr_update_start_datetime_millis  , updated_resource.update_start_datetime_millis)
        #self.failUnlessEqual(fr_ion_institution_id            , updated_resource.ion_institution_id)
        self.failUnlessEqual(fr_ion_title                     , updated_resource.ion_title)
        self.failUnlessEqual(fr_ion_description               , updated_resource.ion_description)



    @defer.inlineCallbacks
    def test_deleteDataResourceNull(self):
        """
        run through the delete code but don't specify any ids.
        """

        log.info("Trying to call deleteDataResource with the wrong GPB")
        delete_req_msg  = yield self.mc.create_instance(DELETE_DATA_RESOURCE_REQ_TYPE)
        result       = yield self.aisc.deleteDataResource(delete_req_msg)
        self.failUnlessEqual(result.MessageType, AIS_RESPONSE_ERROR_TYPE,
                             "deleteDataResource accepted a GPB that was known to be the wrong type")

        log.info("Trying to call deleteDataResource with an empty GPB")
        ais_req_msg  = yield self.mc.create_instance(AIS_REQUEST_MSG_TYPE)
        delete_req_msg  = ais_req_msg.CreateObject(DELETE_DATA_RESOURCE_REQ_TYPE)
        ais_req_msg.message_parameters_reference = delete_req_msg
        result_wrapped = yield self.aisc.deleteDataResource(ais_req_msg)
        self.failUnlessEqual(result_wrapped.MessageType, AIS_RESPONSE_ERROR_TYPE,
                             "deleteDataResource accepted a GPB without a data_source_resource_id list")

# test for deleting an empty list doesn't seem to work because GPBs treat [] and "None" as the same thing
#         log.info("Trying to call deleteDataResource with no ids")
#         delete_req_msg.data_source_resouce_id.append("TEMP")
#         delete_req_msg.data_source_resource_id.pop()
#         result_wrapped = yield self.aisc.deleteDataResource(delete_req_msg)
#         self.failUnlessEqual(result_wrapped.MessageType, AIS_RESPONSE_MSG_TYPE,
#                              "deleteDataResource accepted a GPB without a data_source_resource_id list")

#         log.info("checking number of AIS returns")
#         self.failUnlessEqual(1, len(result_wrapped.message_parameters_reference),
#                              "deleteDataResource returned a GPB with too many 'message_parameters_reference's")

#         log.info("checking number of deleted ids") # (we deleted none, so should be zero!)
#         result = result_wrapped.message_parameters_reference[0]
#         self.failUnlessEqual(0, len(result.successfully_deleted_id),
#                              "We didn't ask for a deletion but apparently one happened...")


    @defer.inlineCallbacks
    def test_deleteDataResourceSample(self):
        """
        @brief try to delete one of the sample data sources
        """
        #yield self._deleteDataResource(SAMPLE_PROFILE_DATA_SOURCE_ID)
        yield self._deleteDataResource(SAMPLE_STATION_DATA_SOURCE_ID)



    @defer.inlineCallbacks
    def _deleteDataResource(self, data_source_id):


        log.info("Creating and wrapping delete request")
        ais_req_msg  = yield self.mc.create_instance(AIS_REQUEST_MSG_TYPE)
        delete_req_msg  = ais_req_msg.CreateObject(DELETE_DATA_RESOURCE_REQ_TYPE)
        ais_req_msg.message_parameters_reference = delete_req_msg


        delete_req_msg.data_source_resource_id.append(data_source_id)


        result_wrapped = yield self.aisc.deleteDataResource(ais_req_msg)

        self.failUnlessEqual(result_wrapped.MessageType, AIS_RESPONSE_MSG_TYPE,
                             "deleteDataResource had an internal failure")

        self.failUnlessEqual(200, result_wrapped.result, "deleteDataResource didn't return 200 OK")
        self.failUnlessEqual(1, len(result_wrapped.message_parameters_reference),
                             "deleteDataResource returned a GPB with too many 'message_parameters_reference's")

        result = result_wrapped.message_parameters_reference[0]

        #check number of deleted ids (we deleted one, so should be one!)
        result = result_wrapped.message_parameters_reference[0]
        num_deletions = len(result.successfully_deleted_id)
        self.failUnlessEqual(1, num_deletions,
                             "Expected 1 deletion, got " + str(num_deletions))

        #check that it's gone
        dsrc = yield self.rc.get_instance(data_source_id)
        self.failUnlessEqual(dsrc.ResourceLifeCycleState, dsrc.RETIRED,
                             "deleteDataResource apparently didn't mark anything retired")

        defer.returnValue(None)




    @defer.inlineCallbacks
    def _createDataResource(self):

        log.info("Trying to call createDataResource with the wrong GPB")
        create_req_msg  = yield self.mc.create_instance(CREATE_DATA_RESOURCE_REQ_TYPE)
        result       = yield self.aisc.createDataResource(create_req_msg)
        self.failUnlessEqual(result.MessageType, AIS_RESPONSE_ERROR_TYPE,
                             "createDataResource accepted a GPB that was known to be the wrong type")

        ais_req_msg = yield self.mc.create_instance(AIS_REQUEST_MSG_TYPE)
        create_req_msg  = ais_req_msg.CreateObject(CREATE_DATA_RESOURCE_REQ_TYPE)
        ais_req_msg.message_parameters_reference = create_req_msg

        #test empty (fields missing) GPB
        yield self._checkCreateFieldAcceptance(ais_req_msg)

        #test full field set but no URLs
        create_req_msg.user_id                       = "A3D5D4A0-7265-4EF2-B0AD-3CE2DC7252D8"
        create_req_msg.source_type                   = create_req_msg.SourceType.NETCDF_S
        create_req_msg.request_type                  = create_req_msg.RequestType.DAP
        create_req_msg.ion_description               = "FIXME: description"
        create_req_msg.ion_institution_id            = "FIXME: institution_id"
        create_req_msg.update_start_datetime_millis  = 30000
        create_req_msg.ion_title                     = "some lame title"
        create_req_msg.update_interval_seconds       = 3600
        yield self._checkCreateFieldAcceptance(ais_req_msg)

        #test too many URLs
        create_req_msg.base_url     = "FIXME"
        create_req_msg.dataset_url  = "http://thredds1.pfeg.noaa.gov/thredds/dodsC/satellite/GR/ssta/1day"
        yield self._checkCreateFieldAcceptance(ais_req_msg)

        create_req_msg.ClearField("base_url")


        #should be ready for actual call that we expect to succeed
        result_wrapped = yield self.aisc.createDataResource(ais_req_msg)

        self.failUnlessEqual(result_wrapped.MessageType, AIS_RESPONSE_MSG_TYPE,
                             "createDataResource had an internal failure")
        self.failUnlessEqual(200, result_wrapped.result, "deleteDataResource didn't return 200 OK")
        self.failUnlessEqual(1, len(result_wrapped.message_parameters_reference),
                             "createDataResource returned a GPB with too many 'message_parameters_reference's")

        result = result_wrapped.message_parameters_reference[0]

        log.info("received data_source_id : " + result.data_source_id)
        log.info("received data_set_id    : " + result.data_set_id)
        log.info("received association_id : " + result.association_id)

        log.info("looking up resource we just added")
        datasource_resource = yield self.rc.get_instance(result.data_source_id)

        self.failUnlessEqual(result.data_source_id, datasource_resource.ResourceIdentity,
                             "Resource ID doesn't match what we created the resource from... STRANGE")

        cm = create_req_msg
        dr = datasource_resource

        log.info("comparing resource with fields from original request")
        self.failUnlessEqual(cm.source_type,                   dr.source_type)
        self.failUnlessEqual(cm.request_type,                  dr.request_type)
        self.failUnlessEqual(cm.ion_description,               dr.ion_description)
        self.failUnlessEqual(cm.ion_institution_id,            dr.ion_institution_id)
        self.failUnlessEqual(cm.update_start_datetime_millis,  dr.update_start_datetime_millis)
        self.failUnlessEqual(cm.ion_title,                     dr.ion_title)
        self.failUnlessEqual(cm.dataset_url,                   dr.dataset_url)

        #test default value for max ingest millis
        self.failUnlessEqual(DEFAULT_MAX_INGEST_MILLIS,        dr.max_ingest_millis)

        #fixme, check association with cm.user_id ... but resource registry handles this?

        yield self._checkAssociatedQuantities(dr, DATASET_RESOURCE_TYPE_ID, "data set", 1)
        yield self._checkAssociatedQuantities(dr, DATARESOURCE_SCHEDULE_TYPE_ID, "scheduled task", 1)

        defer.returnValue(result)


    @defer.inlineCallbacks
    def _checkAssociatedQuantities(self, some_data_resource, type, type_name, expected):
        log.info("checking association between data source and " + type_name)
        associations = yield self._getAssociatedObjects(some_data_resource, HAS_A_ID, DATARESOURCE_SCHEDULE_TYPE_ID)
        self.failUnlessEqual(len(associations), expected, 
                             "got %d associated scheduler tasks instead of %d!" % (len(associations), expected))
        defer.returnValue(None)


    @defer.inlineCallbacks
    def _checkCreateFieldAcceptance(self, req_msg):

        result = yield self.aisc.createDataResource(req_msg)
        self.failUnlessEqual(result.MessageType, AIS_RESPONSE_ERROR_TYPE,
                             "createDataResource accepted a GPB that was known to be lacking data")

        defer.returnValue(None)




    @defer.inlineCallbacks
    def _getAssociatedObjects(self, the_subject, the_predicate, the_object_type):
        """
        @brief get the subject side of an association when you only expect one
        @return id of what you're after
        """

        #can also do obj=
        found = yield self.ac.find_associations(subject=the_subject, \
                                                predicate_or_predicates=HAS_A_ID)

        associations = []
        for a in found:
            mystery_resource = yield self.rc.get_instance(a.ObjectReference.key)
            if the_object_type == mystery_resource.ResourceTypeID.key:
                the_resource = yield self.rc.get_associated_resource_object(a)
                associations.append(the_resource)


        defer.returnValue(associations)

