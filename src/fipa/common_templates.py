from spade.template import Template, ORTemplate
from aioxmpp import JID
from .acl_message import FIPAPerformatives

class CommonTemplates:
    """Common templates for message matching"""

    @staticmethod
    def get_classroom_availability_template():
        """Get a template for PROPOSE and REFUSE for classroom availability"""
        propose_template = Template()
        propose_template.set_metadata("performative", FIPAPerformatives.PROPOSE)
        propose_template.set_metadata("ontology", "classroom-availability")
        
        refuse_template = Template()
        refuse_template.set_metadata("performative", FIPAPerformatives.REFUSE)
        refuse_template.set_metadata("ontology", "classroom-availability")
        
        return propose_template | refuse_template
    
    @staticmethod
    def get_status_query_template():
        """Get a template for status queries"""
        template = Template()
        template.set_metadata("performative", FIPAPerformatives.QUERY_REF)
        template.set_metadata("ontology", "agent-status")
        return template
    
    @staticmethod
    def get_notify_next_professor_template(is_base = False):
        base_name = "negotiation-start-base" if is_base else "negotiation-start"
    
        template = Template()
        template.set_metadata("performative", FIPAPerformatives.INFORM)
        template.set_metadata("conversation-id", base_name)
        # template.set_metadata("content", "START")
        # template.body = "START"
        
        return template
        
    @staticmethod
    def get_room_assigment_template():
        """Get a template for room assignment"""
        cfp = Template()
        cfp.set_metadata("performative", FIPAPerformatives.CFP)
        cfp.set_metadata("protocol", "contract-net")
        
        inform = Template()
        inform.set_metadata("performative", FIPAPerformatives.ACCEPT_PROPOSAL)
        inform.set_metadata("protocol", "contract-net")
        
        return cfp | inform
    
    @staticmethod
    def get_negotiation_template():
        """Get a template for negotiation messages"""
                # Template for CFP responses (proposals and refusals)
        proposal_template = Template()
        proposal_template.set_metadata("performative", FIPAPerformatives.PROPOSE)
        proposal_template.set_metadata("protocol", "contract-net")
        
        refusal_template = Template()
        refusal_template.set_metadata("performative", FIPAPerformatives.REFUSE)
        refusal_template.set_metadata("protocol", "contract-net")
        
        # Template for assignment confirmations
        confirmation_template = Template()
        confirmation_template.set_metadata("performative", FIPAPerformatives.INFORM)
        confirmation_template.set_metadata("protocol", "contract-net")
        
        # Combined template using ORTemplate
        return proposal_template | refusal_template | confirmation_template