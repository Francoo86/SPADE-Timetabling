from spade.template import Template, ORTemplate
from aioxmpp import JID

class CommonTemplates:
    """Common templates for message matching"""

    @staticmethod
    def get_classroom_availability_template():
        """Get a template for PROPOSE and REFUSE for classroom availability"""
        propose_template = Template()
        propose_template.set_metadata("performative", "propose")
        propose_template.set_metadata("ontology", "classroom-availability")
        
        refuse_template = Template()
        refuse_template.set_metadata("performative", "refuse")
        refuse_template.set_metadata("ontology", "classroom-availability")
        
        return propose_template | refuse_template
    
    @staticmethod
    def get_status_query_template():
        """Get a template for status queries"""
        template = Template()
        template.set_metadata("performative", "query-ref")
        template.set_metadata("ontology", "agent-status")
        return template
    
    @staticmethod
    def get_notify_next_professor_template(is_base = False):
        """Get a template for notifying the next professor"""
        base_name = "negotiation-start" if is_base else "negotiation-start-base"
    
        template = Template()
        template.set_metadata("performative", "inform")
        template.set_metadata("conversation-id", base_name)
        template.set_metadata("content", "START")
        
        return template
        