<?xml version="1.0"?>
<xsl:stylesheet version="1.0"
        xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
        xmlns="http://schemas.microsoft.com/wix/2006/wi"
        xmlns:msxsl="urn:schemas-microsoft-com:xslt"
        xmlns:user="local:user"
        xmlns:wix="http://schemas.microsoft.com/wix/2006/wi"
        exclude-result-prefixes="msxsl wix user">

    <xsl:output method="xml" indent="yes" />

    <xsl:strip-space elements="*"/>

    <msxsl:script language="C#" implements-prefix="user"><![CDATA[        
        public string getguid(){
            return Guid.NewGuid().ToString().ToUpper();
        }]]>
    </msxsl:script>

    <!-- generic recursive copy template -->
    <xsl:template match="@*|node()">
        <xsl:copy>
            <xsl:apply-templates select="@*|node()"/>
        </xsl:copy>
    </xsl:template>

    <!-- in a perUser install a file cannot be the component KeyPath -->
    <xsl:template match='wix:Component'>
        <xsl:copy>
            <xsl:apply-templates select="@*|node()"/>
            <!-- this is here because a per user install needs a registry -->
            <!-- entry as its KeyPath and Heat makes the file the KeyPath -->
            <RegistryValue Root="HKCU"
                Key="Software\[Manufacturer]\[ProductName]\Components"
                Type="integer"
                KeyPath="yes"
                Value="1"
                Name="{@Id}"/>
        </xsl:copy>
    </xsl:template>

    <!-- in a perUser install every directory needs an explicit RemoveFolder -->
    <xsl:template match='wix:Directory'>
        <xsl:copy>
            <xsl:apply-templates select="@*|node()"/>
            <!-- create a component for every directory to house the RemoveFolder directive -->
            <!-- also create RegsitryValue to act as the KeyPath for the component -->
            <Component Id="directoryComponent{@Id}" Guid="{user:getguid()}">
                <RegistryValue Root="HKCU"
                    Key="Software\[Manufacturer]\[ProductName]\Directories"
                    Type='integer'
                    KeyPath='yes'
                    Value="1"
                    Name="{@Id}"/>
                <RemoveFolder On='uninstall'
                    Id="remove{@Id}"
                    Directory="{@Id}"/>
            </Component>
        </xsl:copy>
    </xsl:template>

    <!-- This removes the KeyPath attribute form the file nodes in the source document -->
    <xsl:template match='wix:File'>
        <xsl:copy>
            <xsl:apply-templates select="@*[name(.) != 'KeyPath']|node()"/>
        </xsl:copy>
    </xsl:template>

    <xsl:template match="wix:ComponentGroup">
        <xsl:copy>
            <xsl:apply-templates select="@*|node()"/>
            <!-- This creates a reference to all of the components we made in the Directory template -->
            <xsl:for-each select="//wix:Directory">
                <!-- The Id attribute pattern has to match exactly how it is set in the Directory template -->            
                <ComponentRef Id="directoryComponent{@Id}"/>
            </xsl:for-each>
        </xsl:copy>
    </xsl:template>
</xsl:stylesheet>
