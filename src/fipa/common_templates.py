from spade.template import Template, ORTemplate

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